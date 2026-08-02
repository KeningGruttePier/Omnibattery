"""Regression tests for the optional solar-sensor validation."""

from types import SimpleNamespace

from custom_components.omnibattery.config_flow import (
    MarstekVenusConfigFlow,
    OptionsFlowHandler,
)
from custom_components.omnibattery.const import CONF_SOLAR_PRODUCTION_SENSOR


def _hass_with_states(states: dict[str, object]) -> SimpleNamespace:
    """Build the small Home Assistant surface used by the sensor steps."""
    return SimpleNamespace(
        states=SimpleNamespace(get=states.get),
        config_entries=SimpleNamespace(async_entries=lambda _domain: []),
    )


def _state(unit: str) -> SimpleNamespace:
    return SimpleNamespace(attributes={"unit_of_measurement": unit})


async def test_initial_flow_reports_production_sensor_unit_error_on_that_field():
    flow = MarstekVenusConfigFlow()
    flow.hass = _hass_with_states(
        {"sensor.grid_power_va": _state("VA")}
    )

    result = await flow.async_step_user(
        {
            "consumption_sensor": "sensor.grid",
            "max_contracted_power": 7000,
            CONF_SOLAR_PRODUCTION_SENSOR: "sensor.grid_power_va",
        }
    )

    assert result["errors"] == {
        CONF_SOLAR_PRODUCTION_SENSOR: "solar_production_invalid_unit"
    }


async def test_options_flow_reports_production_sensor_unit_error_on_that_field():
    entry = SimpleNamespace(
        entry_id="test-entry",
        data={"consumption_sensor": "sensor.grid", "max_contracted_power": 7000},
        options={},
    )
    flow = OptionsFlowHandler(entry)
    flow.hass = SimpleNamespace(
        states=SimpleNamespace(
            get={"sensor.grid_power_va": _state("VA")}.get
        ),
        config_entries=SimpleNamespace(
            async_get_known_entry=lambda entry_id: (
                entry if entry_id == entry.entry_id else None
            ),
            async_entries=lambda _domain: [],
        ),
    )
    flow.handler = entry.entry_id

    result = await flow.async_step_sensors(
        {
            "consumption_sensor": "sensor.grid",
            "max_contracted_power": 7000,
            CONF_SOLAR_PRODUCTION_SENSOR: "sensor.grid_power_va",
        }
    )

    assert result["errors"] == {
        CONF_SOLAR_PRODUCTION_SENSOR: "solar_production_invalid_unit"
    }
