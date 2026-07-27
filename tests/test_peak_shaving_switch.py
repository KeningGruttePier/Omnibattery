"""Unit tests for the excluded-device peak-shaving runtime switch."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.omnibattery.const import (
    CONF_CAPACITY_PROTECTION_EXCLUDED_DEVICES,
)
from custom_components.omnibattery.switch import (
    CapacityProtectionExcludedDevicesSwitch,
)


def _make_switch(*, enabled: bool, entry_data: dict | None = None):
    controller = SimpleNamespace(
        capacity_protection_excluded_devices=enabled,
    )
    entry = SimpleNamespace(data=dict(entry_data or {}))

    def _update_entry(target, *, data):
        target.data = data

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=_update_entry),
    )
    switch = CapacityProtectionExcludedDevicesSwitch(hass, entry, controller)
    switch.async_write_ha_state = lambda: None
    return switch, controller, entry


def test_switch_reports_controller_state():
    assert _make_switch(enabled=True)[0].is_on is True
    assert _make_switch(enabled=False)[0].is_on is False


def test_turn_on_updates_runtime_and_persists_setting():
    switch, controller, entry = _make_switch(enabled=False)

    asyncio.run(switch.async_turn_on())

    assert controller.capacity_protection_excluded_devices is True
    assert entry.data[CONF_CAPACITY_PROTECTION_EXCLUDED_DEVICES] is True


def test_turn_off_updates_runtime_and_preserves_other_config():
    switch, controller, entry = _make_switch(
        enabled=True,
        entry_data={"unrelated": 42},
    )

    asyncio.run(switch.async_turn_off())

    assert controller.capacity_protection_excluded_devices is False
    assert entry.data[CONF_CAPACITY_PROTECTION_EXCLUDED_DEVICES] is False
    assert entry.data["unrelated"] == 42
