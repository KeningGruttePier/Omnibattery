"""Regression tests for peak-shaving conservation decisions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.omnibattery import ChargeDischargeController
from custom_components.omnibattery.const import (
    CONFIG_NUMBER_DEFINITIONS,
    CONF_CAPACITY_PROTECTION_LIMIT,
)


def test_peak_shaving_limit_supports_20_kw():
    definition = next(
        item for item in CONFIG_NUMBER_DEFINITIONS
        if item["key"] == CONF_CAPACITY_PROTECTION_LIMIT
    )

    assert definition["max"] == 20000
    assert definition["step"] == 100


def _controller(*, previous_power: float):
    ctrl = object.__new__(ChargeDischargeController)
    ctrl.capacity_protection_enabled = True
    ctrl.capacity_protection_excluded_devices = False
    ctrl.capacity_protection_soc_threshold = 25
    ctrl.capacity_protection_limit = 3000
    ctrl.coordinators = [SimpleNamespace(data={"battery_soc": 24})]
    ctrl.previous_power = previous_power
    ctrl._excluded_included_adjustment = 0.0
    ctrl._setpoint_offsets = {"user_target": 0.0}
    ctrl._setpoint_overrides = {}
    ctrl._capacity_protection_active = False
    ctrl._capacity_protection_force_idle = False
    ctrl._capacity_protection_status = {}
    return ctrl


@pytest.mark.parametrize("previous_power", [10.1, -500.0])
def test_conserving_stops_any_existing_battery_command(previous_power):
    ctrl = _controller(previous_power=previous_power)
    grid_power = 321.4 + previous_power

    target, sensor = ctrl._apply_capacity_protection(grid_power, active_target=0.0)

    assert sensor == pytest.approx(grid_power)
    assert target == pytest.approx(grid_power)
    assert ctrl._capacity_protection_force_idle is True
    assert ctrl._capacity_protection_status["action"] == "conserving"


def test_conserving_idle_does_not_request_redundant_stop():
    ctrl = _controller(previous_power=0.0)

    ctrl._apply_capacity_protection(321.4, active_target=0.0)

    assert ctrl._capacity_protection_force_idle is False
    assert ctrl._capacity_protection_status["action"] == "conserving"


def test_solar_surplus_charge_remains_allowed():
    ctrl = _controller(previous_power=10.1)
    grid_power = -89.9

    target, sensor = ctrl._apply_capacity_protection(grid_power, active_target=0.0)

    assert sensor == pytest.approx(grid_power)
    assert target == 0.0
    assert ctrl._capacity_protection_force_idle is False
    assert ctrl._capacity_protection_status["action"] == "charging"


def test_excluded_devices_switch_is_backward_compatible_when_off():
    ctrl = _controller(previous_power=0.0)
    ctrl.coordinators = [SimpleNamespace(data={"battery_soc": 80})]
    ctrl._excluded_included_adjustment = 4000.0

    target, sensor = ctrl._apply_capacity_protection(
        1000.0, active_target=0.0
    )

    assert target == 0.0
    assert sensor == 1000.0
    assert ctrl._capacity_protection_active is False
    assert ctrl._capacity_protection_status["action"] == "idle"


def test_excluded_devices_switch_covers_only_demand_above_peak_limit():
    ctrl = _controller(previous_power=0.0)
    ctrl.coordinators = [SimpleNamespace(data={"battery_soc": 80})]
    ctrl.capacity_protection_excluded_devices = True
    ctrl._excluded_included_adjustment = 4000.0

    target, sensor = ctrl._apply_capacity_protection(
        1000.0, active_target=0.0
    )

    assert target == 0.0
    assert sensor == 2000.0
    assert ctrl._capacity_protection_active is True
    assert ctrl._capacity_protection_status["action"] == "shaving_excluded"
    assert ctrl._capacity_protection_status["excluded_peak_excess"] == 1000


def test_excluded_devices_switch_preserves_normal_home_coverage():
    ctrl = _controller(previous_power=-2000.0)
    ctrl.coordinators = [SimpleNamespace(data={"battery_soc": 80})]
    ctrl.capacity_protection_excluded_devices = True
    ctrl._excluded_included_adjustment = 4000.0

    target, sensor = ctrl._apply_capacity_protection(
        -1000.0, active_target=0.0
    )

    assert target == 0.0
    assert sensor == 0.0
    assert ctrl._capacity_protection_status["action"] == "shaving_excluded"


def test_excluded_devices_below_peak_limit_keep_normal_exclusion():
    ctrl = _controller(previous_power=0.0)
    ctrl.coordinators = [SimpleNamespace(data={"battery_soc": 80})]
    ctrl.capacity_protection_excluded_devices = True
    ctrl._excluded_included_adjustment = 2500.0

    target, sensor = ctrl._apply_capacity_protection(
        1000.0, active_target=0.0
    )

    assert target == 0.0
    assert sensor == 1000.0
    assert ctrl._capacity_protection_active is False
