"""Tests for the Sessy local HTTP driver."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.omnibattery.config_flow import MarstekVenusConfigFlow
from custom_components.omnibattery.drivers.sessy import SessyLocalDriver
from custom_components.omnibattery.sensors.calculated_sensors import (
    MarstekVenusCycleSensor,
    MarstekVenusStoredEnergySensor,
)


class _Response:
    def __init__(self, status=200, data=None):
        self.status = status
        self._data = data or {}

    async def json(self, content_type=None):
        return self._data


class _Context:
    def __init__(self, response): self.response = response
    async def __aenter__(self): return self.response
    async def __aexit__(self, *args): return False


def _session(status=None, energy=None):
    power = status or {"sessy": {"state_of_charge": 0.6, "power": 420, "pack_voltage": 51200, "power_setpoint": 500}, "renewable_energy_phase1": {"power": 100}, "renewable_energy_phase2": {"power": 0}, "renewable_energy_phase3": {"power": -20}}
    session = MagicMock()
    session.closed = False
    session.get.side_effect = [_Context(_Response(200, power)), _Context(_Response(200, energy or {"sessy_energy": {"import_wh": 1200, "export_wh": 800}}))]
    session.post.return_value = _Context(_Response(200))
    return session


@pytest.mark.asyncio
async def test_telemetry_maps_sessy_sign_and_units():
    snapshot = await SessyLocalDriver("sessy.local", session=_session()).read_telemetry()
    assert snapshot["battery_soc"] == 60
    assert snapshot["battery_power"] == -420
    assert snapshot["battery_voltage"] == 51200
    assert snapshot["pv_power"] == 80
    assert snapshot["total_charging_energy"] == 1200


@pytest.mark.asyncio
async def test_setpoint_selects_api_strategy_and_inverts_sign():
    session = _session()
    result = await SessyLocalDriver("sessy.local", session=session).apply_setpoint(700, read_back=False)
    assert result.ok and result.net_power_w == 700
    assert session.post.call_args_list[0].kwargs["json"] == {"strategy": "POWER_STRATEGY_API"}
    assert session.post.call_args_list[1].kwargs["json"] == {"setpoint": -700}


@pytest.mark.asyncio
async def test_setpoint_confirms_against_sessy_power_setpoint():
    status = {"sessy": {"power_setpoint": -400, "power": -350}}
    session = _session(status=status)
    result = await SessyLocalDriver("sessy.local", session=session).apply_setpoint(400)
    assert result.confirmed is True
    assert result.battery_power_w == 350


def test_control_readback_uses_inverse_sessy_sign():
    driver = SessyLocalDriver("sessy.local", session=MagicMock(closed=False))
    assert driver.net_power_from_data({"power_setpoint": 600}) == -600


def test_sessy_uses_configured_capacity_for_stored_energy_and_cycles():
    """Sessy has energy counters but needs its nominal capacity from configuration."""
    data = {
        "battery_soc": 60,
        "battery_total_energy": 5.0,
        "total_charging_energy": 14.0,
        "total_discharging_energy": 12.4,
    }
    stored_energy = object.__new__(MarstekVenusStoredEnergySensor)
    stored_energy.coordinator = SimpleNamespace(data=data)
    stored_energy._dependency_keys = {"soc": "battery_soc", "capacity": "battery_total_energy"}
    cycles = object.__new__(MarstekVenusCycleSensor)
    cycles.coordinator = SimpleNamespace(
        data=data,
        capabilities=SimpleNamespace(cycles_from_discharge_only=True),
    )
    cycles._dependency_keys = {
        "charge": "total_charging_energy",
        "discharge": "total_discharging_energy",
        "capacity": "battery_total_energy",
    }

    assert stored_energy.native_value == 3.0
    assert cycles.native_value == 2.5


def test_sessy_reports_counters_but_not_nominal_capacity():
    capabilities = SessyLocalDriver("sessy.local", session=MagicMock(closed=False)).capabilities
    assert capabilities.has_energy_counters is True
    assert capabilities.has_nominal_capacity is False
    assert capabilities.cycles_from_discharge_only is True


@pytest.mark.asyncio
async def test_sessy_configuration_requests_and_persists_nominal_capacity():
    flow = MarstekVenusConfigFlow()
    flow.config_data = {"num_batteries": 1}
    flow._current_battery_data = {"brand": "sessy"}

    form = await flow.async_step_battery_limits()
    fields = {marker.schema for marker in form["data_schema"].schema}
    assert "battery_capacity_kwh" in fields

    await flow.async_step_battery_limits(
        {
            "max_charge_power": 2200,
            "max_discharge_power": 2200,
            "max_soc": 100,
            "min_soc": 12,
            "charge_hysteresis_percent": 2,
            "backup_offgrid_threshold": 50,
            "battery_capacity_kwh": 5.12,
        }
    )

    assert flow.battery_configs[0]["battery_capacity_kwh"] == 5.12
