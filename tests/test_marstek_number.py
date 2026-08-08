"""Regression tests for Marstek Venus number entity state."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.omnibattery.number import MarstekVenusNumber


def _number_entity(key: str, *, venus_e: bool):
    entity = object.__new__(MarstekVenusNumber)
    entity.definition = {"key": key}
    entity.coordinator = SimpleNamespace(
        data={key: 2500},
        needs_software_power_cap=venus_e,
        user_max_charge_power=500,
        user_max_discharge_power=1200,
    )
    return entity


def test_venus_e_number_shows_user_charge_cap_after_polling():
    entity = _number_entity("max_charge_power", venus_e=True)

    assert entity.native_value == 500.0


def test_venus_e_number_shows_user_discharge_cap_after_polling():
    entity = _number_entity("max_discharge_power", venus_e=True)

    assert entity.native_value == 1200.0


def test_non_venus_e_number_keeps_polled_register_value():
    entity = _number_entity("max_charge_power", venus_e=False)

    assert entity.native_value == 2500
