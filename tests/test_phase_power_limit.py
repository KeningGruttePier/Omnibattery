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
    CONF_THREE_PHASE_ENABLED,
    PHASE_L1,
    PHASE_L2,
)
from custom_components.omnibattery.control.phase_power_limit import (
    PhasePowerLimiter,
    calculate_phase_budgets,
    normalize_power_sensor_state,
)
from custom_components.omnibattery.config_flow import _validate_phase_protection


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


def _limiter(states, coordinators, *, now=None):
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
    controller = FakeController(coordinators)
    hass = SimpleNamespace(states=FakeStates(states))
    return PhasePowerLimiter(
        hass,
        entry,
        controller,
        max_age_s=65,
    )


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


def test_allocation_rounds_down_to_phase_budget_and_uses_healthy_phase():
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

    allocation = limiter.allocate(4000, [b1, b2], [b1, b2], True)

    assert allocation[b1] == 750
    assert allocation[b2] == 3250
    assert sum(allocation.values()) == 4000

    # If L1 telemetry is unavailable, its battery is held at zero while L2
    # continues up to its own safe phase budget.
    limiter.hass.states._states["sensor.l1"] = _state("unavailable", now=now)
    limiter.begin_cycle()
    allocation = limiter.allocate(4000, [b1, b2], [b1, b2], True)
    assert allocation[b1] == 0
    assert allocation[b2] == 4000


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

    invalid = {**valid, CONF_PHASE_2_POWER_SENSOR: "sensor.l1", CONF_PHASE_3_MAX_POWER: 0}
    errors = _validate_phase_protection(hass, invalid)
    assert errors[CONF_PHASE_1_POWER_SENSOR] == "phase_sensors_must_differ"
    assert errors[CONF_PHASE_2_POWER_SENSOR] == "phase_sensors_must_differ"
    assert errors[CONF_PHASE_3_MAX_POWER] == "phase_limit_must_be_positive"

    missing = {**valid, CONF_PHASE_1_POWER_SENSOR: None, CONF_PHASE_2_POWER_SENSOR: None}
    missing_errors = _validate_phase_protection(hass, missing)
    assert missing_errors[CONF_PHASE_1_POWER_SENSOR] == "phase_sensor_not_found"
    assert missing_errors[CONF_PHASE_2_POWER_SENSOR] == "phase_sensor_not_found"
