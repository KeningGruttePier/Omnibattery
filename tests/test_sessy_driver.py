"""Tests for the Sessy local HTTP driver."""

from unittest.mock import MagicMock

import pytest

from custom_components.omnibattery.drivers.sessy import SessyLocalDriver


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
