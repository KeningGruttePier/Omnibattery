"""Per-phase AC power safety limits for three-phase installations.

The global controller intentionally knows nothing about the phase meters.  This
module is a safety envelope around automatic battery assignments: it reconstructs
the phase load from the live grid reading and the measured AC battery power, then
limits the next battery order in either direction.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_BATTERY_PHASE,
    CONF_METER_INVERTED,
    CONF_PHASE_1_MAX_POWER,
    CONF_PHASE_1_POWER_SENSOR,
    CONF_PHASE_2_MAX_POWER,
    CONF_PHASE_2_POWER_SENSOR,
    CONF_PHASE_3_MAX_POWER,
    CONF_PHASE_3_POWER_SENSOR,
    CONF_THREE_PHASE_ENABLED,
    DEFAULT_THREE_PHASE_ENABLED,
    MAX_SENSOR_STALE_S,
    PHASE_CONFIG,
    PHASE_L1,
    PHASE_L2,
    PHASE_L3,
    PHASE_VALUES,
)

_LOGGER = logging.getLogger(__name__)

PHASE_SENSOR_KEYS = {
    PHASE_L1: CONF_PHASE_1_POWER_SENSOR,
    PHASE_L2: CONF_PHASE_2_POWER_SENSOR,
    PHASE_L3: CONF_PHASE_3_POWER_SENSOR,
}
PHASE_LIMIT_KEYS = {
    PHASE_L1: CONF_PHASE_1_MAX_POWER,
    PHASE_L2: CONF_PHASE_2_MAX_POWER,
    PHASE_L3: CONF_PHASE_3_MAX_POWER,
}
PHASE_LABELS = {PHASE_L1: "L1", PHASE_L2: "L2", PHASE_L3: "L3"}
ROUNDING_W = 5


@dataclass(frozen=True)
class PhaseSensorReading:
    """Normalized phase meter reading and its safety status."""

    value_w: float | None
    reason: str | None = None
    age_s: float | None = None


def _state_timestamp(state: Any) -> datetime | None:
    """Return the newest publication timestamp available on a HA state."""
    if state is None:
        return None
    return getattr(state, "last_reported", None) or getattr(
        state, "last_updated", None
    )


def normalize_power_sensor_state(
    state: Any,
    *,
    meter_inverted: bool = False,
    now: datetime | None = None,
    max_age_s: float = MAX_SENSOR_STALE_S,
) -> PhaseSensorReading:
    """Normalize a W/kW sensor using the integration's grid-meter convention.

    Positive values mean import and negative values mean export.  A missing
    timestamp is accepted for duck-typed unit tests and old HA state objects;
    current Home Assistant ``State`` objects always provide one.
    """
    if state is None:
        return PhaseSensorReading(None, "sensor_not_found")

    raw_state = getattr(state, "state", None)
    if raw_state in (None, "unknown", "unavailable"):
        return PhaseSensorReading(None, "sensor_unavailable")

    try:
        value = float(raw_state)
    except (TypeError, ValueError):
        return PhaseSensorReading(None, "sensor_not_numeric")
    if not math.isfinite(value):
        return PhaseSensorReading(None, "sensor_not_numeric")

    attributes = getattr(state, "attributes", {}) or {}
    unit = attributes.get("unit_of_measurement")
    if unit == "kW":
        value *= 1000.0
    elif unit != "W":
        return PhaseSensorReading(None, "sensor_invalid_unit")

    timestamp = _state_timestamp(state)
    age_s = None
    if timestamp is not None:
        reference = now or dt_util.utcnow()
        try:
            age_s = max(0.0, (reference - timestamp).total_seconds())
        except (TypeError, ValueError):
            return PhaseSensorReading(None, "sensor_invalid_timestamp")
        if age_s > max_age_s:
            return PhaseSensorReading(None, "sensor_stale", age_s)

    if meter_inverted:
        value = -value
    return PhaseSensorReading(value, age_s=age_s)


def calculate_phase_budgets(
    grid_w: float,
    battery_power_w: float,
    limit_w: float,
) -> dict[str, float]:
    """Return base load and safe charge/discharge budgets for one phase.

    ``battery_power_w`` follows the controller convention: positive is charge
    and negative is discharge.  The grid reading already includes that battery
    power, hence the explicit base-load reconstruction.
    """
    base_w = float(grid_w) - float(battery_power_w)
    limit = max(0.0, float(limit_w))
    return {
        "base_w": base_w,
        "charge_budget_w": max(0.0, limit - float(grid_w) + float(battery_power_w)),
        "discharge_budget_w": max(0.0, limit + float(grid_w) - float(battery_power_w)),
    }


def _round_down(value: float, granularity: int = ROUNDING_W) -> int:
    """Round a safety value down so rounding can never cross a limit."""
    if value <= 0:
        return 0
    return int(math.floor((float(value) + 1e-9) / granularity) * granularity)


class PhasePowerLimiter:
    """Read phase telemetry and constrain aggregate automatic assignments."""

    def __init__(
        self,
        hass: Any,
        config_entry: Any,
        controller: Any | None = None,
        *,
        max_age_s: float = MAX_SENSOR_STALE_S,
        rounding_w: int = ROUNDING_W,
    ) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.controller = controller
        self.max_age_s = max_age_s
        self.rounding_w = rounding_w
        self.enabled = False
        self.meter_inverted = False
        self._phase_settings: dict[str, tuple[str | None, float]] = {}
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._planned: dict[Any, tuple[bool, int]] = {}
        self._last_log_signature: dict[str, tuple[Any, ...]] = {}
        self._manual_warning_created = False
        self.refresh_config()

    @property
    def phase_values(self) -> tuple[str, ...]:
        """Normalized phase values accepted by runtime configuration."""
        return PHASE_VALUES

    def refresh_config(self) -> None:
        """Reload configuration and update coordinator phase metadata."""
        data = getattr(self.config_entry, "data", {}) or {}
        self.enabled = bool(data.get(CONF_THREE_PHASE_ENABLED, DEFAULT_THREE_PHASE_ENABLED))
        self.meter_inverted = bool(data.get(CONF_METER_INVERTED, False))
        self._phase_settings = {}
        for phase in PHASE_VALUES:
            sensor_key, limit_key = PHASE_CONFIG[phase]
            raw_limit = data.get(limit_key)
            try:
                limit = float(raw_limit)
            except (TypeError, ValueError):
                limit = 0.0
            self._phase_settings[phase] = (data.get(sensor_key), limit)

        for coordinator in getattr(self.controller, "coordinators", []) or []:
            if hasattr(coordinator, "_config_entry"):
                battery_data = next(
                    (
                        battery
                        for battery in data.get("batteries", [])
                        if battery.get("host") == getattr(coordinator, "host", None)
                        and battery.get("port") == getattr(coordinator, "port", None)
                        and battery.get("slave_id", 1)
                        == getattr(coordinator, "slave_id", 1)
                    ),
                    None,
                )
                if battery_data is not None:
                    coordinator.phase = battery_data.get(CONF_BATTERY_PHASE, "")

    def begin_cycle(self) -> None:
        """Forget distribution plans from the previous control cycle."""
        self._planned.clear()

    def _battery_phase(self, coordinator: Any) -> str | None:
        phase = getattr(coordinator, "phase", None)
        if phase not in PHASE_VALUES:
            phase = getattr(coordinator, CONF_BATTERY_PHASE, None)
        return phase if phase in PHASE_VALUES else None

    def _battery_power(self, coordinator: Any) -> float:
        """Read measured AC power in the controller's +charge/-discharge form."""
        if self.controller is not None:
            getter = getattr(self.controller, "_coordinator_delivered_power", None)
            if getter is not None:
                try:
                    value = getter(coordinator)
                    if value is not None and math.isfinite(float(value)):
                        return float(value)
                except (TypeError, ValueError):
                    pass

        data = getattr(coordinator, "data", None) or {}
        ac_power = data.get("ac_power")
        if ac_power is not None:
            try:
                return -float(ac_power)
            except (TypeError, ValueError):
                return 0.0
        battery_power = data.get("battery_power")
        try:
            return float(battery_power) if battery_power is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _read_phase(self, phase: str) -> tuple[PhaseSensorReading, float]:
        sensor_id, limit = self._phase_settings.get(phase, (None, 0.0))
        state = self.hass.states.get(sensor_id) if sensor_id else None
        reading = normalize_power_sensor_state(
            state,
            meter_inverted=self.meter_inverted,
            max_age_s=self.max_age_s,
        )
        battery_power = sum(
            self._battery_power(coordinator)
            for coordinator in getattr(self.controller, "coordinators", []) or []
            if self._battery_phase(coordinator) == phase
        )
        return reading, battery_power

    def phase_snapshot(self, phase: str) -> dict[str, Any]:
        """Return the current phase calculation, including degradation reason."""
        sensor_id, limit = self._phase_settings.get(phase, (None, 0.0))
        snapshot: dict[str, Any] = {
            "phase": phase,
            "sensor": sensor_id,
            "reading_w": None,
            "limit_w": limit if limit > 0 else None,
            "base_w": None,
            "charge_budget_w": 0.0,
            "discharge_budget_w": 0.0,
            "assigned_power_w": 0.0,
            "requested_power_w": 0.0,
            "degraded": False,
            "reason": None,
        }
        if not self.enabled:
            snapshot["reason"] = "disabled"
            self._snapshots[phase] = snapshot
            return snapshot
        if limit <= 0:
            snapshot.update({"degraded": True, "reason": "invalid_limit"})
            self._log_state_change(snapshot)
            self._snapshots[phase] = snapshot
            return snapshot

        reading, battery_power = self._read_phase(phase)
        if reading.value_w is None:
            snapshot.update({"degraded": True, "reason": reading.reason})
            self._log_state_change(snapshot)
            self._snapshots[phase] = snapshot
            return snapshot

        budgets = calculate_phase_budgets(reading.value_w, battery_power, limit)
        snapshot.update(
            {
                "reading_w": reading.value_w,
                "base_w": budgets["base_w"],
                "charge_budget_w": _round_down(budgets["charge_budget_w"], self.rounding_w),
                "discharge_budget_w": _round_down(budgets["discharge_budget_w"], self.rounding_w),
            }
        )
        self._snapshots[phase] = snapshot
        return snapshot

    def all_snapshots(self) -> dict[str, dict[str, Any]]:
        """Refresh and return all phase diagnostics."""
        return {phase: self.phase_snapshot(phase) for phase in PHASE_VALUES}

    def _individual_limit(self, coordinator: Any, is_charging: bool) -> float:
        if self.controller is not None:
            getter = getattr(self.controller, "_battery_power_limit", None)
            if getter is not None:
                try:
                    return max(0.0, float(getter(coordinator, is_charging)))
                except (TypeError, ValueError):
                    return 0.0
        key = "max_charge_power" if is_charging else "max_discharge_power"
        try:
            return max(0.0, float(getattr(coordinator, key, 0)))
        except (TypeError, ValueError):
            return 0.0

    def _phase_capacity(
        self,
        phase: str,
        batteries: Iterable[Any],
        is_charging: bool,
    ) -> int:
        snapshot = self.phase_snapshot(phase)
        if snapshot["degraded"]:
            return 0
        individual = sum(
            _round_down(self._individual_limit(coordinator, is_charging), self.rounding_w)
            for coordinator in batteries
        )
        budget = (
            snapshot["charge_budget_w"]
            if is_charging
            else snapshot["discharge_budget_w"]
        )
        return min(_round_down(individual, self.rounding_w), int(budget))

    def _ordered_unique(
        self,
        selected_batteries: Iterable[Any],
        available_batteries: Iterable[Any],
    ) -> list[Any]:
        result: list[Any] = []
        for coordinator in [*selected_batteries, *available_batteries]:
            if coordinator not in result:
                result.append(coordinator)
        return result

    def _allocate_group(
        self,
        total: int,
        batteries: list[Any],
        is_charging: bool,
    ) -> dict[Any, int]:
        """Allocate in proportion to individual caps, using only round-down."""
        limits = {
            coordinator: _round_down(
                self._individual_limit(coordinator, is_charging), self.rounding_w
            )
            for coordinator in batteries
        }
        capacity = sum(limits.values())
        total = min(max(0, int(total)), capacity)
        if total <= 0 or capacity <= 0:
            return {coordinator: 0 for coordinator in batteries}

        allocation = {
            coordinator: _round_down(
                total * limits[coordinator] / capacity,
                self.rounding_w,
            )
            for coordinator in batteries
        }
        remaining = total - sum(allocation.values())
        # Fill whole 5 W increments in selection order.  This preserves the
        # normal SOC ordering while keeping the aggregate below the budget.
        while remaining >= self.rounding_w:
            changed = False
            for coordinator in batteries:
                room = limits[coordinator] - allocation[coordinator]
                if room >= self.rounding_w and remaining >= self.rounding_w:
                    allocation[coordinator] += self.rounding_w
                    remaining -= self.rounding_w
                    changed = True
            if not changed:
                break
        return allocation

    def allocate(
        self,
        total_power: float,
        selected_batteries: list[Any],
        available_batteries: list[Any],
        is_charging: bool,
    ) -> dict[Any, int]:
        """Allocate a request across safe phase and individual capacities."""
        ordered = self._ordered_unique(selected_batteries, available_batteries)
        allocation = {coordinator: 0 for coordinator in ordered}
        if not self.enabled:
            return allocation

        valid = [
            coordinator
            for coordinator in ordered
            if self._battery_phase(coordinator) in PHASE_VALUES
        ]
        phase_order: list[str] = []
        for coordinator in valid:
            phase = self._battery_phase(coordinator)
            if phase not in phase_order:
                phase_order.append(phase)

        phase_batteries = {
            phase: [
                coordinator for coordinator in valid if self._battery_phase(coordinator) == phase
            ]
            for phase in phase_order
        }
        phase_capacities = {
            phase: self._phase_capacity(
                phase, phase_batteries[phase], is_charging
            )
            for phase in phase_order
        }
        requested = max(0.0, float(total_power))
        if self.controller is not None:
            clamp = getattr(self.controller, "_clamp_to_system_capacity", None)
            if clamp is not None:
                try:
                    requested = float(
                        clamp(requested, ordered, is_charging)
                    )
                except (TypeError, ValueError):
                    pass
        remaining = min(_round_down(requested, self.rounding_w), sum(phase_capacities.values()))

        # The selector's first phase has priority.  If its safety budget is
        # exhausted, the remaining request naturally falls through to other
        # healthy phases; same-phase batteries are added before another phase.
        for phase in phase_order:
            if remaining <= 0:
                break
            phase_remaining_before = remaining
            phase_request = min(remaining, phase_capacities[phase])
            group_alloc = self._allocate_group(
                phase_request,
                phase_batteries[phase],
                is_charging,
            )
            for coordinator, value in group_alloc.items():
                allocation[coordinator] = value
            assigned = sum(group_alloc.values())
            snapshot = self._snapshots[phase]
            snapshot["requested_power_w"] = phase_request
            snapshot["assigned_power_w"] = (
                assigned if is_charging else -assigned
            )
            if phase_remaining_before > phase_capacities[phase]:
                self._log_limit(snapshot, phase_remaining_before, assigned)
            remaining -= assigned

        # A missing/invalid phase is deliberately represented as zero here.  The
        # next guard in _set_battery_power covers automatic routes that bypass
        # this normal distribution path.
        self._planned = {
            coordinator: (is_charging, value)
            for coordinator, value in allocation.items()
        }
        active = [coordinator for coordinator, value in allocation.items() if value > 0]
        if self.controller is not None:
            if is_charging:
                self.controller._active_charge_batteries = active
            else:
                self.controller._active_discharge_batteries = active
        for snapshot in self._snapshots.values():
            self._log_state_change(snapshot)
        return allocation

    def _commanded_direction_power(self, coordinator: Any, is_charging: bool) -> float:
        key = "commanded_charge_power" if is_charging else "commanded_discharge_power"
        try:
            return max(0.0, float(getattr(coordinator, key, 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    def limit_single_command(
        self,
        coordinator: Any,
        charge_power: float,
        discharge_power: float,
    ) -> tuple[int, int]:
        """Apply the aggregate phase budget to a non-distribution command."""
        if not self.enabled or (charge_power <= 0 and discharge_power <= 0):
            return max(0, int(charge_power)), max(0, int(discharge_power))
        if charge_power > 0 and discharge_power > 0:
            return 0, 0

        is_charging = charge_power > 0
        requested = charge_power if is_charging else discharge_power
        planned = self._planned.get(coordinator)
        if planned is not None and planned[0] == is_charging:
            if abs(float(planned[1]) - float(requested)) < self.rounding_w:
                return (planned[1], 0) if is_charging else (0, planned[1])

        phase = self._battery_phase(coordinator)
        if phase not in PHASE_VALUES:
            self._set_degraded_reason(coordinator, "battery_phase_missing")
            return 0, 0
        snapshot = self.phase_snapshot(phase)
        if snapshot["degraded"]:
            return 0, 0

        budget = (
            snapshot["charge_budget_w"]
            if is_charging
            else snapshot["discharge_budget_w"]
        )
        other_power = sum(
            self._commanded_direction_power(other, is_charging)
            for other in getattr(self.controller, "coordinators", []) or []
            if other is not coordinator and self._battery_phase(other) == phase
        )
        own_limit = _round_down(
            self._individual_limit(coordinator, is_charging), self.rounding_w
        )
        allowed = _round_down(
            min(float(requested), max(0.0, float(budget) - other_power), own_limit),
            self.rounding_w,
        )
        if allowed < requested:
            snapshot["requested_power_w"] = requested
            snapshot["assigned_power_w"] = allowed if is_charging else -allowed
            self._log_limit(snapshot, requested, allowed)
        return (allowed, 0) if is_charging else (0, allowed)

    def _set_degraded_reason(self, coordinator: Any, reason: str) -> None:
        phase = self._battery_phase(coordinator)
        if phase not in PHASE_VALUES:
            phase = "unassigned"
        snapshot = self._snapshots.setdefault(
            phase,
            {
                "phase": phase,
                "reading_w": None,
                "limit_w": None,
                "base_w": None,
                "charge_budget_w": 0.0,
                "discharge_budget_w": 0.0,
                "assigned_power_w": 0.0,
                "requested_power_w": 0.0,
                "degraded": True,
                "reason": reason,
            },
        )
        snapshot.update({"degraded": True, "reason": reason})
        self._log_state_change(snapshot)

    def _log_state_change(self, snapshot: dict[str, Any]) -> None:
        phase = snapshot.get("phase", "?")
        signature = (
            snapshot.get("degraded"),
            snapshot.get("reason"),
            round(float(snapshot.get("assigned_power_w") or 0) / 50),
            round(float(snapshot.get("requested_power_w") or 0) / 50),
        )
        previous = self._last_log_signature.get(phase)
        if previous == signature:
            return
        self._last_log_signature[phase] = signature
        if snapshot.get("degraded"):
            _LOGGER.warning(
                "Three-phase protection %s degraded: sensor=%s reason=%s; "
                "automatic assignments on this phase are limited to 0 W",
                PHASE_LABELS.get(phase, phase),
                snapshot.get("sensor"),
                snapshot.get("reason"),
            )
        elif previous and previous[0]:
            _LOGGER.info(
                "Three-phase protection %s recovered: reading=%.0fW limit=%.0fW",
                PHASE_LABELS.get(phase, phase),
                snapshot.get("reading_w") or 0,
                snapshot.get("limit_w") or 0,
            )

    def _log_limit(
        self,
        snapshot: dict[str, Any],
        requested: float,
        allowed: float,
    ) -> None:
        phase = snapshot.get("phase", "?")
        signature = (
            round(float(snapshot.get("reading_w") or 0) / 50),
            round(float(snapshot.get("limit_w") or 0) / 50),
            round(float(requested) / 50),
            round(float(allowed) / 50),
        )
        log_key = f"limit:{phase}"
        if self._last_log_signature.get(log_key) == signature:
            return
        self._last_log_signature[log_key] = signature
        _LOGGER.info(
            "Three-phase protection %s limit active: reading=%.0fW limit=%.0fW "
            "request=%.0fW result=%.0fW",
            PHASE_LABELS.get(phase, phase),
            snapshot.get("reading_w") or 0,
            snapshot.get("limit_w") or 0,
            requested,
            allowed,
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return configuration and current per-phase safety state."""
        phases = self.all_snapshots()
        return {
            "enabled": self.enabled,
            "meter_inverted": self.meter_inverted,
            "sensors": {
                PHASE_SENSOR_KEYS[phase]: self._phase_settings.get(phase, (None, 0.0))[0]
                for phase in PHASE_VALUES
            },
            "limits_w": {
                PHASE_LIMIT_KEYS[phase]: self._phase_settings.get(phase, (None, 0.0))[1]
                for phase in PHASE_VALUES
            },
            "phases": phases,
            "manual_mode_warning": self._manual_warning_created,
        }

    def update_manual_mode_warning(self, entry_id: str, enabled: bool) -> None:
        """Expose the documented manual-register escape as a Repairs warning."""
        issue_id = f"three_phase_manual_mode_{entry_id}"
        if self.enabled:
            ir.async_create_issue(
                self.hass,
                "omnibattery",
                issue_id,
                is_fixable=False,
                is_persistent=True,
                issue_domain="omnibattery",
                severity=ir.IssueSeverity.WARNING,
                translation_key="three_phase_manual_mode",
                translation_placeholders={
                    "manual_enabled": "enabled" if enabled else "available",
                },
            )
            self._manual_warning_created = True
        else:
            ir.async_delete_issue(self.hass, "omnibattery", issue_id)
            self._manual_warning_created = False
