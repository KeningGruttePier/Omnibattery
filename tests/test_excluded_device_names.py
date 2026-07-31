"""Regression coverage for excluded-device control names (#187)."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.omnibattery.infra.entity_naming import excluded_device_name


def _hass(states: dict) -> SimpleNamespace:
    return SimpleNamespace(states=SimpleNamespace(get=states.get))


def test_excluded_device_name_uses_home_assistant_friendly_name():
    state = SimpleNamespace(attributes={"friendly_name": "Wallbox garage"})

    assert excluded_device_name(
        _hass({"sensor.wallbox_power": state}),
        {"power_sensor": "sensor.wallbox_power"},
    ) == "Wallbox garage"


def test_excluded_device_name_falls_back_to_readable_entity_id():
    assert excluded_device_name(
        _hass({}),
        {"activity_sensor": "binary_sensor.ev_charging"},
    ) == "Ev Charging"
