"""Regression tests for the three-phase options flow."""

from types import SimpleNamespace

from homeassistant.const import CONF_NAME

from custom_components.omnibattery.config_flow import OptionsFlowHandler
from custom_components.omnibattery.const import (
    CONF_BATTERY_PHASE,
    CONF_PHASE_1_CURRENT_SENSOR,
    CONF_PHASE_1_FUSE_SIZE,
    CONF_THREE_PHASE_ENABLED,
    PHASE_L1,
    PHASE_L2,
)


def _options_flow(entry: SimpleNamespace) -> OptionsFlowHandler:
    """Initialize an options flow with the Home Assistant surface it needs."""
    flow = OptionsFlowHandler(entry)
    flow.hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity_id: SimpleNamespace(
                attributes={"unit_of_measurement": "A"}
            )
        ),
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda entry_id: (
                entry if entry_id == entry.entry_id else None
            )
        ),
    )
    flow.handler = entry.entry_id
    return flow


async def test_options_flow_reasks_battery_phases_when_already_enabled():
    """Editing current protection must confirm every battery's physical phase."""
    entry = SimpleNamespace(
        entry_id="three-phase-entry",
        data={
            CONF_THREE_PHASE_ENABLED: True,
            "batteries": [
                {CONF_NAME: "Battery 1", CONF_BATTERY_PHASE: PHASE_L1},
                {CONF_NAME: "Battery 2", CONF_BATTERY_PHASE: PHASE_L2},
            ],
        },
        options={},
    )
    flow = _options_flow(entry)

    result = await flow.async_step_three_phase(
        {
            CONF_PHASE_1_CURRENT_SENSOR: "sensor.phase_l1",
            CONF_PHASE_1_FUSE_SIZE: 25,
        }
    )

    assert result["step_id"] == "phase_assignments"
    assert result["description_placeholders"] == {
        "battery_num": "1",
        "battery_name": "Battery 1",
    }

    result = await flow.async_step_phase_assignments(
        {CONF_BATTERY_PHASE: PHASE_L2}
    )

    assert result["step_id"] == "phase_assignments"
    assert result["description_placeholders"] == {
        "battery_num": "2",
        "battery_name": "Battery 2",
    }
