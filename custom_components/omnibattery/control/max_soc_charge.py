"""Top-of-charge management for a normal 100% target (MaxSocChargeManager).

Despite the legacy ``_normal_balance_*`` attribute names this module does NOT
drive active cell balancing. It manages the final stretch of a normal max-SOC
(100%) charge:

- Charge-power taper near the top cell voltage (CV-like ramp-down).
- SOC hysteresis, owned by the main controller, stops future charging once the
  top voltage is reached.
- SOC recalibration: keep charging past the top-voltage threshold when the BMS reports a low SOC
  at full cell voltage (coulomb-counter drift) until the BMS itself cuts off.
- After a cutoff above 3.60 V, wait for the cell to relax to 3.57 V and make one
  additional 200 W charge attempt before latching the recalibration session.
- Passive cell-delta measurement at the top, reported to the balance monitor.

The latched state (the ``_normal_balance_*`` dicts) stays on the controller
because weekly_full_charge.py and the main control loop read and mutate it;
this module reads/writes it by reference via ``self._controller``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import (
    CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
    NORMAL_BALANCE_CHARGE_POWER_W,
    NORMAL_BALANCE_MEASURE_WAIT_SECONDS,
    NORMAL_BALANCE_PAUSE_CELL_VOLTAGE,
    NORMAL_BALANCE_RECAL_CUTOFF_CYCLES,
    NORMAL_BALANCE_RECAL_CUTOFF_POWER_W,
    NORMAL_BALANCE_RECAL_INVERTER_STANDBY,
    NORMAL_BALANCE_RECAL_RETRY_CELL_VOLTAGE,
    NORMAL_BALANCE_RECAL_SOC_THRESHOLD,
    NORMAL_BALANCE_TAPER_CELL_VOLTAGE,
    NORMAL_BALANCE_TAPER_EXIT_CELL_VOLTAGE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class MaxSocChargeManager:
    """Top-of-charge taper, SOC recalibration and cell-delta measurement."""

    def __init__(self, hass: "HomeAssistant", controller: Any) -> None:
        self._hass = hass
        self._controller = controller

    def reset_if_new_day(self) -> None:
        """Reset top-of-charge latched state at the local day boundary."""
        c = self._controller
        today = dt_util.now().date()
        if today == c._normal_balance_date:
            return

        c._normal_balance_date = today
        c._normal_balance_voltage_tapered.clear()
        c._normal_balance_phases.clear()
        c._normal_balance_measure_started.clear()
        c._normal_balance_last_delta_v.clear()
        c._normal_balance_recal_override.clear()
        c._normal_balance_recal_cutoff_count.clear()
        c._normal_balance_recal_latched.clear()
        c._normal_balance_recal_retry_pending.clear()
        c._normal_balance_recal_retry_active.clear()
        c._normal_balance_recal_first_cutoff_voltage.clear()

    @staticmethod
    def _cell_delta_v(data: dict) -> float | None:
        """Return current max-min cell delta in V when both voltages are known."""
        vmax = data.get("max_cell_voltage")
        vmin = data.get("min_cell_voltage")
        if vmax is None or vmin is None:
            return None
        try:
            return round(float(vmax) - float(vmin), 4)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _taper_enabled(coordinator) -> bool:
        """Return True when this battery uses full-charge voltage tapering."""
        return bool(
            getattr(
                coordinator,
                CONF_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
                DEFAULT_FULL_CHARGE_VOLTAGE_TAPER_ENABLED,
            )
        )

    def _taper_applies(self, coordinator) -> bool:
        """Return True when taper is enabled for this coordinator."""
        if getattr(coordinator, "battery_manual_mode_enabled", False):
            return False
        if not self._taper_enabled(coordinator):
            return False
        return True

    def _zone_active(self, coordinator) -> bool:
        """Return True when the battery is in the normal top-balancing zone."""
        if not self._taper_applies(coordinator):
            return False

        data = coordinator.data or {}
        vmax = data.get("max_cell_voltage")
        try:
            if vmax is not None and float(vmax) >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                return True
        except (TypeError, ValueError):
            return False
        return False

    @staticmethod
    def _bms_cut_signature(coordinator, data: dict) -> bool:
        """Return True when the BMS refuses a charge we are actually commanding.

        <=10 W + Standby on its own is ambiguous: a battery that is merely idle,
        not allocated charge this cycle, reads exactly the same without being
        full. Gating on the commanded set-point separates a real BMS cut from
        "nobody asked it to charge". This is the same gate used by the weekly
        full-charge path.
        """
        power = data.get("battery_power")
        inv = data.get("inverter_state")
        commanded = getattr(coordinator, "commanded_charge_power", 0) or 0
        try:
            return (
                power is not None
                and inv is not None
                and commanded > NORMAL_BALANCE_RECAL_CUTOFF_POWER_W
                and float(power) <= NORMAL_BALANCE_RECAL_CUTOFF_POWER_W
                and int(inv) == NORMAL_BALANCE_RECAL_INVERTER_STANDBY
            )
        except (TypeError, ValueError):
            return False

    def _compute_recal_override(self, coordinator, vmax_f: float, soc) -> bool:
        """Decide whether to keep charging past the top-voltage threshold to recalibrate SOC.

        Called while the max cell is in the top taper zone (down to the taper
        voltage, so the BMS-cutoff counter keeps advancing as the cell relaxes
        after a cut). A low reported SOC at full cell voltage may mean the BMS
        coulomb counter has drifted, so keep charging (at the tapered power)
        until the BMS itself cuts off. If that first cutoff happens above 3.60 V
        while SOC is still below 100%, wait for the cell to relax to 3.57 V and
        make one additional 200 W attempt. Some firmware keeps the previous SOC
        after cutoff; the latch clears when the battery leaves the top zone (see
        refresh_blocks).
        """
        c = self._controller

        data = coordinator.data or {}

        # A first cutoff above the pause voltage can leave the top cell too high
        # for the BMS to accept another command immediately.  Keep the battery
        # idle until it relaxes to 3.57 V, then open exactly one retry window.
        # This branch intentionally uses <100% rather than the initial <99%
        # trigger: a cutoff at 99% still qualifies for the one extra attempt.
        retry_pending = c._normal_balance_recal_retry_pending.get(coordinator, False)
        retry_active = c._normal_balance_recal_retry_active.get(coordinator, False)
        if retry_pending:
            if soc is None or soc >= 100:
                c._normal_balance_recal_retry_pending.pop(coordinator, None)
                return False
            if vmax_f > NORMAL_BALANCE_RECAL_RETRY_CELL_VOLTAGE:
                return False
            c._normal_balance_recal_retry_pending.pop(coordinator, None)
            c._normal_balance_recal_retry_active[coordinator] = True
            c._normal_balance_recal_cutoff_count.pop(coordinator, None)
            retry_active = True
            _LOGGER.info(
                "%s: SOC recalibration cutoff confirmed above %.2f V; cell relaxed to %.2f V — "
                "starting one %d W retry",
                coordinator.name,
                NORMAL_BALANCE_PAUSE_CELL_VOLTAGE,
                NORMAL_BALANCE_RECAL_RETRY_CELL_VOLTAGE,
                NORMAL_BALANCE_CHARGE_POWER_W,
            )

        if retry_active:
            if soc is None or soc >= 100:
                c._normal_balance_recal_retry_active.pop(coordinator, None)
                c._normal_balance_recal_cutoff_count.pop(coordinator, None)
                return False

            if self._bms_cut_signature(coordinator, data):
                count = c._normal_balance_recal_cutoff_count.get(coordinator, 0) + 1
                c._normal_balance_recal_cutoff_count[coordinator] = count
                if count >= NORMAL_BALANCE_RECAL_CUTOFF_CYCLES:
                    c._normal_balance_recal_retry_active.pop(coordinator, None)
                    c._normal_balance_recal_cutoff_count.pop(coordinator, None)
                    _LOGGER.info(
                        "%s: One-shot SOC recalibration retry ended after BMS cutoff at "
                        "vmax=%.3f V, SOC=%s%%",
                        coordinator.name,
                        vmax_f,
                        soc,
                    )
                    return False
            else:
                power = data.get("battery_power")
                try:
                    accepting = (
                        power is not None
                        and float(power) > NORMAL_BALANCE_RECAL_CUTOFF_POWER_W
                    )
                except (TypeError, ValueError):
                    accepting = False
                if accepting:
                    # The retry is still in progress; only a new refusal can end it.
                    c._normal_balance_recal_cutoff_count.pop(coordinator, None)
            return True

        if soc is None or soc >= NORMAL_BALANCE_RECAL_SOC_THRESHOLD:
            c._normal_balance_recal_cutoff_count.pop(coordinator, None)
            c._normal_balance_recal_first_cutoff_voltage.pop(coordinator, None)
            return False
        if c._normal_balance_recal_latched.get(coordinator):
            return False

        if self._bms_cut_signature(coordinator, data):
            count = c._normal_balance_recal_cutoff_count.get(coordinator, 0) + 1
            c._normal_balance_recal_cutoff_count[coordinator] = count
            previous_vmax = c._normal_balance_recal_first_cutoff_voltage.get(coordinator)
            c._normal_balance_recal_first_cutoff_voltage[coordinator] = (
                vmax_f if previous_vmax is None else max(previous_vmax, vmax_f)
            )
            if count >= NORMAL_BALANCE_RECAL_CUTOFF_CYCLES:
                c._normal_balance_recal_latched[coordinator] = True
                c._normal_balance_recal_cutoff_count.pop(coordinator, None)
                cutoff_vmax = c._normal_balance_recal_first_cutoff_voltage[coordinator]
                if cutoff_vmax > NORMAL_BALANCE_PAUSE_CELL_VOLTAGE and soc < 100:
                    c._normal_balance_recal_retry_pending[coordinator] = True
                    _LOGGER.info(
                        "%s: BMS cutoff during SOC recalibration at vmax=%.3f V, SOC=%s%% — "
                        "waiting for %.2f V before one retry",
                        coordinator.name,
                        cutoff_vmax,
                        soc,
                        NORMAL_BALANCE_RECAL_RETRY_CELL_VOLTAGE,
                    )
                else:
                    _LOGGER.info(
                        "%s: BMS cutoff during SOC recalibration at vmax=%.3f V, SOC=%s%% — "
                        "holding; no retry required",
                        coordinator.name,
                        cutoff_vmax,
                        soc,
                    )
                return False
        else:
            power = data.get("battery_power")
            try:
                accepting = (
                    power is not None
                    and float(power) > NORMAL_BALANCE_RECAL_CUTOFF_POWER_W
                )
            except (TypeError, ValueError):
                accepting = False
            if accepting:
                # The battery is accepting charge, so it is genuinely not full.
                c._normal_balance_recal_cutoff_count.pop(coordinator, None)
                c._normal_balance_recal_first_cutoff_voltage.pop(coordinator, None)
            # When idle or not commanded, freeze the counter: neither increment
            # nor reset it. A confirmed cutoff stops the command, and resetting
            # here would erase the evidence that is about to latch the cutoff.
        return True

    def _clear_recal_state(self, coordinator) -> None:
        """Drop all SOC-recalibration state for a battery (session ended)."""
        c = self._controller
        c._normal_balance_recal_override.pop(coordinator, None)
        c._normal_balance_recal_cutoff_count.pop(coordinator, None)
        c._normal_balance_recal_latched.pop(coordinator, None)
        c._normal_balance_recal_retry_pending.pop(coordinator, None)
        c._normal_balance_recal_retry_active.pop(coordinator, None)
        c._normal_balance_recal_first_cutoff_voltage.pop(coordinator, None)

    def refresh_blocks(self) -> None:
        """Update normal high-SOC charge protection blockers.

        The normal mode does not force charging. It only stops charge while the
        max cell is at the 100% top voltage; SOC hysteresis decides when future
        charging is allowed.
        """
        c = self._controller
        self.reset_if_new_day()

        for coordinator in c.coordinators:
            if getattr(coordinator, "battery_manual_mode_enabled", False):
                # Preserve normal top-of-charge state while the user owns the
                # battery; it is reevaluated after returning to automatic mode.
                c.remove_charge_block("max_soc", coordinator=coordinator)
                c.remove_charge_block("charge_hysteresis", coordinator=coordinator)
                continue
            data = coordinator.data or {}
            if not self._taper_applies(coordinator):
                c._normal_balance_voltage_tapered.pop(coordinator, None)
                self._clear_recal_state(coordinator)
                continue

            if not data:
                c._normal_balance_voltage_tapered.pop(coordinator, None)
                c._normal_balance_recal_override.pop(coordinator, None)
                continue

            in_zone = self._zone_active(coordinator)
            vmax_raw = (coordinator.data or {}).get("max_cell_voltage")
            try:
                vmax_now = float(vmax_raw) if vmax_raw is not None else None
            except (TypeError, ValueError):
                vmax_now = None
            # Hysteresis: only clear the taper latch once the cell has dropped to the
            # exit threshold (below entry), not the moment it slips under 3.48 V at
            # low charge power. This prevents full-power ↔ tapered-power oscillation.
            if not in_zone and (vmax_now is None or vmax_now < NORMAL_BALANCE_TAPER_EXIT_CELL_VOLTAGE):
                c._normal_balance_voltage_tapered.pop(coordinator, None)
            if not in_zone:
                # Battery has dropped out of the top zone: end any recal session so
                # a later full charge can recalibrate again.
                self._clear_recal_state(coordinator)

            vmax = data.get("max_cell_voltage")
            current_soc = data.get("battery_soc")
            try:
                vmax_f = float(vmax) if vmax is not None else None
            except (TypeError, ValueError):
                vmax_f = None
            weekly_active = hasattr(c, "_weekly_charge_mgr") and c._weekly_full_charge_unlocked()

            if vmax_f is not None:
                if in_zone and vmax_f >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                    c._normal_balance_voltage_tapered[coordinator] = True
            # SOC recalibration starts only once the cell has reached the top
            # voltage (or a commanded charge has already hit the BMS cutoff). It
            # then continues through the taper zone while the cell relaxes.
            override = False
            bms_cut_signature = in_zone and self._bms_cut_signature(coordinator, data)
            recal_started = (
                vmax_f is not None
                and in_zone
                and (
                    vmax_f >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE
                    or bms_cut_signature
                    or c._normal_balance_recal_override.get(coordinator, False)
                    or coordinator in c._normal_balance_recal_cutoff_count
                    or c._normal_balance_recal_latched.get(coordinator, False)
                    or c._normal_balance_recal_retry_pending.get(coordinator, False)
                    or c._normal_balance_recal_retry_active.get(coordinator, False)
                )
            )
            if not weekly_active and recal_started:
                override = self._compute_recal_override(coordinator, vmax_f, current_soc)
            c._normal_balance_recal_override[coordinator] = override

    def apply_charge_taper(self, coordinator, limit: int) -> int:
        """Cap the per-battery charge limit to the taper power once near the top."""
        c = self._controller
        if not self._taper_applies(coordinator):
            return limit

        data = coordinator.data or {}
        max_cell_voltage = data.get("max_cell_voltage")
        voltage_tapered = c._normal_balance_voltage_tapered
        voltage_taper_latched = voltage_tapered.get(coordinator, False)
        if max_cell_voltage is not None:
            try:
                max_cell_voltage_f = float(max_cell_voltage)
                if max_cell_voltage_f >= NORMAL_BALANCE_TAPER_CELL_VOLTAGE:
                    voltage_taper_latched = True
                    voltage_tapered[coordinator] = True
                elif max_cell_voltage_f < NORMAL_BALANCE_TAPER_EXIT_CELL_VOLTAGE:
                    voltage_tapered.pop(coordinator, None)
                    voltage_taper_latched = False
                if voltage_taper_latched:
                    limit = min(limit, NORMAL_BALANCE_CHARGE_POWER_W)
            except (TypeError, ValueError):
                pass

        return limit

    def get_status(self) -> dict:
        """Return top-of-charge diagnostics for the integration status sensor."""
        c = self._controller
        status = {}
        for coordinator in c.coordinators:
            data = coordinator.data or {}
            if not data:
                continue
            status[coordinator.name] = {
                "enabled": self._taper_enabled(coordinator),
                "in_zone": self._zone_active(coordinator),
                "max_cell_voltage": data.get("max_cell_voltage"),
                "min_cell_voltage": data.get("min_cell_voltage"),
                "delta_V": self._cell_delta_v(data),
                "voltage_taper_latched": c._normal_balance_voltage_tapered.get(
                    coordinator, False
                ),
                "normal_balance_phase": c._normal_balance_phases.get(coordinator),
                "soc_recal_active": c._normal_balance_recal_override.get(coordinator, False),
                "soc_recal_bms_cutoff": c._normal_balance_recal_latched.get(coordinator, False),
                "soc_recal_retry_pending": c._normal_balance_recal_retry_pending.get(
                    coordinator, False
                ),
                "soc_recal_retry_active": c._normal_balance_recal_retry_active.get(
                    coordinator, False
                ),
                "soc_recal_first_cutoff_voltage": c._normal_balance_recal_first_cutoff_voltage.get(
                    coordinator
                ),
                "charge_limit_w": c._battery_power_limit(coordinator, True),
            }
        return status

    async def handle_measurement(self) -> bool:
        """Measure cell delta after any 100% target reaches top voltage."""
        c = self._controller
        active_details = {}
        took_over = False
        active_coordinators: set = set()

        # During an active weekly full charge the taper must drive the battery
        # all the way to the real BMS cutoff. The 60 s measurement hold (0 W
        # while vmax >= pause voltage) would otherwise cap the cell at 3.60 V and
        # stall an imbalanced pack there forever — it relaxes below 3.60 V at 0 W,
        # resumes, climbs back, and ping-pongs without ever reaching the cutoff.
        # The delta-V diagnostic is still captured once at completion.
        weekly_active = (
            hasattr(c, "_weekly_charge_mgr") and c._weekly_full_charge_unlocked()
        )

        for coordinator in c.coordinators:
            if coordinator.data is None or not self._taper_applies(coordinator):
                continue
            if weekly_active:
                # Let the weekly taper charge to the BMS cutoff; don't hold/measure.
                c._normal_balance_phases.pop(coordinator, None)
                c._normal_balance_measure_started.pop(coordinator, None)
                continue
            if c._normal_balance_recal_override.get(coordinator):
                # SOC recalibration in progress: let PD keep charging to the BMS
                # cutoff instead of holding/measuring at the top voltage.
                c._normal_balance_phases.pop(coordinator, None)
                c._normal_balance_measure_started.pop(coordinator, None)
                continue
            if coordinator in c._normal_balance_phases:
                active_coordinators.add(coordinator)
                continue
            try:
                vmax = float(coordinator.data.get("max_cell_voltage"))
            except (TypeError, ValueError):
                continue
            if vmax >= NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                c._normal_balance_phases[coordinator] = "WAIT_MEASURE"
                c._normal_balance_measure_started[coordinator] = dt_util.utcnow()
                active_coordinators.add(coordinator)

        for coordinator in list(c._normal_balance_phases):
            if getattr(coordinator, "battery_manual_mode_enabled", False):
                continue
            if coordinator not in active_coordinators:
                c._normal_balance_phases.pop(coordinator, None)
                c._normal_balance_measure_started.pop(coordinator, None)

        for coordinator in active_coordinators:
            data = coordinator.data or {}
            try:
                vmax = float(data.get("max_cell_voltage"))
                vmin = float(data.get("min_cell_voltage"))
            except (TypeError, ValueError):
                c._normal_balance_phases.pop(coordinator, None)
                c._normal_balance_measure_started.pop(coordinator, None)
                continue

            phase = c._normal_balance_phases.get(coordinator, "WAIT_MEASURE")
            charge_power = 0
            discharge_power = 0
            delta_v = round(vmax - vmin, 4)
            if phase == "WAIT_MEASURE":
                started = c._normal_balance_measure_started.setdefault(
                    coordinator,
                    dt_util.utcnow(),
                )
                if (dt_util.utcnow() - started).total_seconds() >= NORMAL_BALANCE_MEASURE_WAIT_SECONDS:
                    c._normal_balance_last_delta_v[coordinator] = delta_v
                    phase = "MEASURED"
                    c._normal_balance_phases[coordinator] = phase
                    if c._balance_monitor is not None:
                        await c._balance_monitor.async_record_top_balance_measurement(
                            coordinator,
                            vmax,
                            vmin,
                            data.get("battery_soc"),
                            phase="top_charge_3_55v",
                        )
                    _LOGGER.info(
                        "%s: normal 100%% balance measurement delta=%.4f V at vmax=%.3f V",
                        coordinator.name,
                        delta_v,
                        vmax,
                    )
            if phase == "MEASURED" and vmax < NORMAL_BALANCE_PAUSE_CELL_VOLTAGE:
                c._normal_balance_phases.pop(coordinator, None)
                c._normal_balance_measure_started.pop(coordinator, None)
                await c._set_battery_power(coordinator, 0, 0)
                continue

            details = {
                "phase": phase.lower(),
                "max_cell_voltage": round(vmax, 3),
                "min_cell_voltage": round(vmin, 3),
                "delta_V": delta_v,
                "charge_w": charge_power,
                "discharge_w": discharge_power,
            }
            active_details[coordinator.name] = details
            took_over = True

            await c._set_battery_power(
                coordinator,
                charge_power,
                discharge_power,
                ignore_charge_blockers={
                    "charge_delay",
                    "time_slot_charge",
                    "max_soc",
                    "charge_hysteresis",
                },
                ignore_discharge_blockers={
                    "time_slot_discharge",
                    "price_discharge",
                    "min_soc",
                },
            )

        if active_details:
            _LOGGER.debug("Normal max-SOC active balancing: %s", active_details)
        return took_over
