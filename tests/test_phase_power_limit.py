from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.omnibattery.const import (
    CONF_METER_INVERTED,
    CONF_PHASE_1_MAX_POWER,
    CONF_PHASE_1_POWER_SENSOR,
    CONF_PHASE_2_MAX_POWER,
    CONF_PHASE_2_POWER_SENSOR,
    CONF_PHASE_3_MAX_POWER,
    CONF_PHASE_3_POWER_SENSOR,
    CONF_SLOT_ENABLED,
    CONF_SLOT_MODE,
    CONF_TIME_SLOTS,
    CONF_THREE_PHASE_ENABLED,
    PHASE_L1,
    PHASE_L2,
    PHASE_L3,
    SLOT_MODE_MANUAL,
)
from custom_components.omnibattery.control import (
    phase_power_limit as phase_power_limit_module,
)
from custom_components.omnibattery.control.phase_power_limit import (
    PhasePowerLimiter,
    calculate_phase_budgets,
    normalize_power_sensor_state,
)
from custom_components.omnibattery.config_flow import (
    _phase_protection_schema,
    _validate_phase_protection,
)


class FakeStates:
    def __init__(self, states: dict[str, object]):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeCoordinator:
    def __init__(self, name: str, phase: str, max_power: int = 4000):
        self.name = name
        self.phase = phase
        self.data = {"battery_power": 0}
        self.max_charge_power = max_power
        self.max_discharge_power = max_power
        self.commanded_charge_power = 0
        self.commanded_discharge_power = 0


class FakeController:
    def __init__(self, coordinators):
        self.coordinators = coordinators
        self._active_charge_batteries = []
        self._active_discharge_batteries = []

    @staticmethod
    def _coordinator_delivered_power(coordinator):
        return float(coordinator.data.get("battery_power", 0))

    @staticmethod
    def _battery_power_limit(coordinator, is_charging):
        return coordinator.max_charge_power if is_charging else coordinator.max_discharge_power

    @staticmethod
    def _clamp_to_system_capacity(total, _batteries, _is_charging):
        return total


def _state(value, unit="W", now=None, age_s=0):
    now = now or datetime.now(timezone.utc)
    return SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit},
        last_reported=now - timedelta(seconds=age_s),
        last_updated=now - timedelta(seconds=age_s),
    )


def _limiter(states, coordinators, *, now=None, configured_phases=None):
    entry = SimpleNamespace(
        data={
            CONF_THREE_PHASE_ENABLED: True,
            CONF_METER_INVERTED: False,
            CONF_PHASE_1_POWER_SENSOR: "sensor.l1",
            CONF_PHASE_2_POWER_SENSOR: "sensor.l2",
            CONF_PHASE_3_POWER_SENSOR: "sensor.l3",
            CONF_PHASE_1_MAX_POWER: 5750,
            CONF_PHASE_2_MAX_POWER: 5750,
            CONF_PHASE_3_MAX_POWER: 5750,
        }
    )
    if configured_phases is not None:
        phase_fields = {
            PHASE_L1: (CONF_PHASE_1_POWER_SENSOR, CONF_PHASE_1_MAX_POWER),
            PHASE_L2: (CONF_PHASE_2_POWER_SENSOR, CONF_PHASE_2_MAX_POWER),
            PHASE_L3: (CONF_PHASE_3_POWER_SENSOR, CONF_PHASE_3_MAX_POWER),
        }
        for phase, (sensor_key, limit_key) in phase_fields.items():
            if phase not in configured_phases:
                entry.data[sensor_key] = None
                entry.data[limit_key] = None
    controller = FakeController(coordinators)
    hass = SimpleNamespace(states=FakeStates(states))
    return PhasePowerLimiter(
        hass,
        entry,
        controller,
        max_age_s=65,
    )


def _warning_limiter(*, phase_enabled=True, slots=None):
    entry = SimpleNamespace(
        data={
            CONF_THREE_PHASE_ENABLED: phase_enabled,
            CONF_TIME_SLOTS: slots or [],
        }
    )
    return PhasePowerLimiter(SimpleNamespace(), entry)


def _capture_warning_repairs(monkeypatch):
    created = []
    deleted = []
    monkeypatch.setattr(
        phase_power_limit_module.ir,
        "async_create_issue",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )
    monkeypatch.setattr(
        phase_power_limit_module.ir,
        "async_delete_issue",
        lambda *args, **kwargs: deleted.append((args, kwargs)),
    )
    return created, deleted


def test_manual_warning_is_cleared_without_a_manual_bypass(monkeypatch):
    created, deleted = _capture_warning_repairs(monkeypatch)
    limiter = _warning_limiter()

    limiter.update_manual_mode_warning("entry", False)

    assert created == []
    assert deleted[0][0][2] == "three_phase_manual_mode_entry"
    assert limiter._manual_warning_created is False


def test_manual_warning_covers_manual_mode_and_manual_slots(monkeypatch):
    created, deleted = _capture_warning_repairs(monkeypatch)
    limiter = _warning_limiter()

    limiter.update_manual_mode_warning("entry", True)
    assert len(created) == 1

    limiter.update_manual_mode_warning("entry", False)
    assert len(deleted) == 1

    limiter.config_entry.data[CONF_TIME_SLOTS] = [
        {CONF_SLOT_ENABLED: True, CONF_SLOT_MODE: SLOT_MODE_MANUAL}
    ]
    limiter.update_manual_mode_warning("entry", False)
    assert len(created) == 2

    limiter.config_entry.data[CONF_TIME_SLOTS][0][CONF_SLOT_ENABLED] = False
    limiter.update_manual_mode_warning("entry", False)
    assert len(deleted) == 2


def test_manual_warning_stays_cleared_when_three_phase_protection_is_disabled(
    monkeypatch,
):
    created, deleted = _capture_warning_repairs(monkeypatch)
    limiter = _warning_limiter(phase_enabled=False)

    limiter.update_manual_mode_warning("entry", True)

    assert created == []
    assert deleted[0][0][2] == "three_phase_manual_mode_entry"


def test_phase_budget_uses_controller_battery_sign():
    no_battery = calculate_phase_budgets(5000, 0, 5750)
    assert no_battery["charge_budget_w"] == 750

    budgets = calculate_phase_budgets(5000, 1000, 5750)

    assert budgets == {
        "base_w": 4000,
        "charge_budget_w": 1750,
        "discharge_budget_w": 9750,
    }

    export = calculate_phase_budgets(-5200, -1000, 5750)
    assert export["base_w"] == -4200
    assert export["discharge_budget_w"] == 1550


def test_sensor_normalization_handles_kw_inversion_and_staleness():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)

    assert normalize_power_sensor_state(
        _state(1.5, "kW", now), now=now
    ).value_w == 1500
    assert normalize_power_sensor_state(
        _state(1500, "W", now), meter_inverted=True, now=now
    ).value_w == -1500
    stale = normalize_power_sensor_state(
        _state(1500, "W", now, age_s=66), now=now
    )
    assert stale.value_w is None
    assert stale.reason == "sensor_stale"


def test_allocation_caps_phase_and_moves_overflow_to_healthy_phase():
    now = datetime.now(timezone.utc)
    b1 = FakeCoordinator("L1 battery", PHASE_L1)
    b2 = FakeCoordinator("L2 battery", PHASE_L2)
    limiter = _limiter(
        {
            "sensor.l1": _state(5000, now=now),
            "sensor.l2": _state(1000, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [b1, b2],
    )

    allocation = limiter.limit_allocation({b1: 2000, b2: 2000}, True, [b1, b2])

    assert allocation[b1] == 750
    assert allocation[b2] == 3250
    assert sum(allocation.values()) == 4000

    # If L1 telemetry is unavailable, its battery is held at zero while L2
    # accepts the rejected portion up to its own safe capacity.
    limiter.hass.states._states["sensor.l1"] = _state("unavailable", now=now)
    limiter.begin_cycle()
    allocation = limiter.limit_allocation({b1: 2000, b2: 2000}, True, [b1, b2])
    assert allocation[b1] == 0
    assert allocation[b2] == 4000


def test_allocation_never_adds_an_unselected_battery():
    now = datetime.now(timezone.utc)
    selected = FakeCoordinator("Selected", PHASE_L1)
    unselected = FakeCoordinator("Unselected", PHASE_L1)
    limiter = _limiter(
        {
            "sensor.l1": _state(0, now=now),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [selected, unselected],
    )

    allocation = limiter.limit_allocation(
        {selected: 100},
        True,
        [selected, unselected],
    )

    assert allocation[selected] == 100
    assert allocation[unselected] == 0


def test_overflow_activates_fallback_only_after_selected_phase_is_capped():
    now = datetime.now(timezone.utc)
    selected = FakeCoordinator("Selected L1", PHASE_L1)
    fallback = FakeCoordinator("Fallback L2", PHASE_L2)
    limiter = _limiter(
        {
            "sensor.l1": _state(5000, now=now),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [selected, fallback],
    )

    allocation = limiter.limit_allocation(
        {selected: 2000},
        True,
        [selected, fallback],
    )

    assert allocation == {selected: 750, fallback: 1250}


def test_allocation_preserves_normal_proportional_split_below_phase_cap():
    now = datetime.now(timezone.utc)
    b1 = FakeCoordinator("First", PHASE_L1)
    b2 = FakeCoordinator("Second", PHASE_L1)
    limiter = _limiter(
        {
            "sensor.l1": _state(0, now=now),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [b1, b2],
    )

    assert limiter.limit_allocation({b1: 750, b2: 250}, True, [b1, b2]) == {
        b1: 750,
        b2: 250,
    }


def test_degraded_phase_is_detected_without_a_new_sensor_event():
    now = datetime.now(timezone.utc)
    battery = FakeCoordinator("L1 battery", PHASE_L1)
    limiter = _limiter(
        {
            "sensor.l1": _state(0, now=now, age_s=66),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [battery],
    )

    assert limiter.has_degraded_phase() is True
    assert limiter.limit_allocation({battery: 500}, True) == {battery: 0}


def test_unconfigured_phases_are_optional_but_fail_safe_for_assigned_batteries():
    now = datetime.now(timezone.utc)
    l1_battery = FakeCoordinator("L1 battery", PHASE_L1)
    limiter = _limiter(
        {
            "sensor.l1": _state(0, now=now),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [l1_battery],
        configured_phases={PHASE_L1},
    )

    assert limiter.has_degraded_phase() is False
    assert limiter.phase_snapshot(PHASE_L2)["reason"] == "not_configured"

    l2_battery = FakeCoordinator("L2 battery", PHASE_L2)
    limiter.controller.coordinators.append(l2_battery)
    limiter.begin_cycle()

    assert limiter.has_degraded_phase() is True
    assert limiter.limit_allocation({l2_battery: 500}, True) == {l2_battery: 0}


def test_direct_command_guard_blocks_unassigned_and_caps_valid_phase():
    now = datetime.now(timezone.utc)
    b1 = FakeCoordinator("L1 battery", PHASE_L1)
    unassigned = FakeCoordinator("Unassigned", "")
    limiter = _limiter(
        {
            "sensor.l1": _state(5000, now=now),
            "sensor.l2": _state(0, now=now),
            "sensor.l3": _state(0, now=now),
        },
        [b1, unassigned],
    )

    assert limiter.limit_single_command(b1, 2000, 0) == (750, 0)
    assert limiter.limit_single_command(unassigned, 1000, 0) == (0, 0)


def test_config_validation_rejects_duplicate_sensors_and_bad_units():
    hass = SimpleNamespace(
        states=FakeStates(
            {
                "sensor.l1": _state(100, "W"),
                "sensor.l2": _state(100, "kW"),
                "sensor.l3": _state(100, "W"),
            }
        )
    )
    valid = {
        CONF_PHASE_1_POWER_SENSOR: "sensor.l1",
        CONF_PHASE_2_POWER_SENSOR: "sensor.l2",
        CONF_PHASE_3_POWER_SENSOR: "sensor.l3",
        CONF_PHASE_1_MAX_POWER: 5750,
        CONF_PHASE_2_MAX_POWER: 5750,
        CONF_PHASE_3_MAX_POWER: 5750,
    }
    assert _validate_phase_protection(hass, valid) == {}

    two_phase = {
        key: valid[key]
        for key in (
            CONF_PHASE_1_POWER_SENSOR,
            CONF_PHASE_1_MAX_POWER,
            CONF_PHASE_2_POWER_SENSOR,
            CONF_PHASE_2_MAX_POWER,
        )
    }
    assert _validate_phase_protection(hass, two_phase) == {}

    invalid = {**valid, CONF_PHASE_2_POWER_SENSOR: "sensor.l1", CONF_PHASE_3_MAX_POWER: 0}
    errors = _validate_phase_protection(hass, invalid)
    assert errors[CONF_PHASE_1_POWER_SENSOR] == "phase_sensors_must_differ"
    assert errors[CONF_PHASE_2_POWER_SENSOR] == "phase_sensors_must_differ"
    assert errors[CONF_PHASE_3_MAX_POWER] == "phase_limit_must_be_positive"

    missing = {**valid}
    for key in (
        CONF_PHASE_1_POWER_SENSOR,
        CONF_PHASE_1_MAX_POWER,
        CONF_PHASE_2_POWER_SENSOR,
        CONF_PHASE_2_MAX_POWER,
    ):
        missing.pop(key)
    missing_errors = _validate_phase_protection(hass, missing)
    assert missing_errors == {}

    partial = {
        CONF_PHASE_1_POWER_SENSOR: "sensor.l1",
        CONF_PHASE_1_MAX_POWER: None,
    }
    partial_errors = _validate_phase_protection(hass, partial)
    assert partial_errors[CONF_PHASE_1_MAX_POWER] == "phase_sensor_and_limit_required"

    orphan_limit_errors = _validate_phase_protection(
        hass,
        {CONF_PHASE_1_MAX_POWER: 5750},
    )
    assert orphan_limit_errors[CONF_PHASE_1_POWER_SENSOR] == (
        "phase_sensor_and_limit_required"
    )


def test_phase_form_accepts_a_single_configured_phase():
    assert _phase_protection_schema()(
        {
            CONF_PHASE_1_POWER_SENSOR: "sensor.l1",
            CONF_PHASE_1_MAX_POWER: 5750,
        }
    ) == {
        CONF_PHASE_1_POWER_SENSOR: "sensor.l1",
        CONF_PHASE_1_MAX_POWER: 5750.0,
    }
