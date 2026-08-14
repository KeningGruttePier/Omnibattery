"""Tests for the live three-phase protection controls."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.omnibattery.const import (
    CONF_BATTERY_PHASE,
    CONF_THREE_PHASE_ENABLED,
    DOMAIN,
    PHASE_L2,
    PHASE_UNASSIGNED,
)
from custom_components.omnibattery.select import BatteryPhaseSelect
from custom_components.omnibattery.sensor import ThreePhaseProtectionSensor
from custom_components.omnibattery.switch import (
    ThreePhaseProtectionSwitch,
    async_setup_entry,
)


def _phase_select(*, enabled: bool = True, phase: str = PHASE_UNASSIGNED):
    coordinator = SimpleNamespace(
        device_key="battery_1",
        name="Battery 1",
        phase=phase,
        available=True,
        battery_device_info={"name": "Battery 1"},
        persist_battery_config=Mock(),
    )
    entry = SimpleNamespace(data={CONF_THREE_PHASE_ENABLED: enabled})
    entity = BatteryPhaseSelect(SimpleNamespace(), entry, coordinator)
    entity.async_write_ha_state = Mock()
    return entity, coordinator, entry


def test_battery_phase_select_normalizes_unassigned_and_is_gated_by_protection():
    entity, _coordinator, entry = _phase_select(enabled=False, phase="")

    assert entity.current_option == PHASE_UNASSIGNED
    assert entity.available is False

    entry.data[CONF_THREE_PHASE_ENABLED] = True
    assert entity.available is True


def test_battery_phase_select_updates_runtime_and_persists():
    entity, coordinator, _entry = _phase_select()

    asyncio.run(entity.async_select_option(PHASE_L2))

    assert coordinator.phase == PHASE_L2
    coordinator.persist_battery_config.assert_called_once_with(
        CONF_BATTERY_PHASE, PHASE_L2
    )
    assert entity.current_option == PHASE_L2


def _protection_switch(*, enabled: bool = False):
    limiter = SimpleNamespace(enabled=enabled)
    controller = SimpleNamespace(_phase_power_limiter=limiter)
    entry = SimpleNamespace(data={"unrelated": 42})

    def _update_entry(target, *, data):
        target.data = data

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=_update_entry)
    )
    entity = ThreePhaseProtectionSwitch(hass, entry, controller)
    entity.async_write_ha_state = Mock()
    return entity, limiter, entry


def test_three_phase_protection_switch_changes_runtime_and_config():
    entity, limiter, entry = _protection_switch()

    assert entity.is_on is False
    assert entity.icon == "mdi:shield-check-outline"
    asyncio.run(entity.async_turn_on())
    assert limiter.enabled is True
    assert entry.data[CONF_THREE_PHASE_ENABLED] is True
    assert entry.data["unrelated"] == 42

    asyncio.run(entity.async_turn_off())
    assert limiter.enabled is False
    assert entry.data[CONF_THREE_PHASE_ENABLED] is False


def test_three_phase_protection_sensor_has_a_valid_icon():
    controller = SimpleNamespace(
        _phase_power_limiter=SimpleNamespace(
            diagnostics=lambda: {"state": "disabled"}
        )
    )
    entity = ThreePhaseProtectionSensor(SimpleNamespace(), SimpleNamespace(), controller)

    assert entity.icon == "mdi:shield-check-outline"


def test_three_phase_protection_switch_is_created_when_disabled():
    entry = SimpleNamespace(entry_id="test-entry", data={CONF_THREE_PHASE_ENABLED: False})
    controller = SimpleNamespace(
        _phase_power_limiter=SimpleNamespace(enabled=False),
        weekly_full_charge_enabled=False,
    )
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: {"coordinators": [], "controller": controller}}}
    )
    added: list = []

    asyncio.run(async_setup_entry(hass, entry, lambda entities: added.extend(entities)))

    assert any(isinstance(entity, ThreePhaseProtectionSwitch) for entity in added)
