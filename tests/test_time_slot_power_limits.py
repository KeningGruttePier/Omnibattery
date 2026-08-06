"""Regression tests for time-slot power override selector limits."""

from custom_components.omnibattery.config_flow import _build_slot_step_b_schema
from custom_components.omnibattery.const import SLOT_BATTERY_SCOPE_ALL


def _power_maxes(schema) -> dict[str, int]:
    """Return selector maxima keyed by their form field."""
    return {
        marker.schema: selector.config["max"]
        for marker, selector in schema.schema.items()
        if "max_" in marker.schema
    }


def test_time_slot_power_override_uses_external_driver_limits():
    """Anker/SOLIX limits are persisted instead of defaulting to 2500 W."""
    schema = _build_slot_step_b_schema(
        needs_soc=False,
        needs_power=True,
        scope=SLOT_BATTERY_SCOPE_ALL,
        battery_configs=[
            {
                "brand": "anker",
                "max_charge_power": 3500,
                "max_discharge_power": 3500,
            }
        ],
        defaults={},
    )

    assert _power_maxes(schema) == {
        "battery_1__max_charge_power_w": 3500,
        "battery_1__max_discharge_power_w": 3500,
    }


def test_time_slot_power_override_keeps_directional_limits():
    """Asymmetric external-driver ceilings remain distinct in the form."""
    schema = _build_slot_step_b_schema(
        needs_soc=False,
        needs_power=True,
        scope=SLOT_BATTERY_SCOPE_ALL,
        battery_configs=[
            {
                "brand": "sessy",
                "max_charge_power": 2200,
                "max_discharge_power": 1700,
            }
        ],
        defaults={},
    )

    assert _power_maxes(schema) == {
        "battery_1__max_charge_power_w": 2200,
        "battery_1__max_discharge_power_w": 1700,
    }


def test_time_slot_power_override_keeps_marstek_version_envelope():
    """Versioned Marstek models continue to use their physical envelope."""
    schema = _build_slot_step_b_schema(
        needs_soc=False,
        needs_power=True,
        scope=SLOT_BATTERY_SCOPE_ALL,
        battery_configs=[
            {
                "battery_version": "v2",
                "max_charge_power": 3500,
                "max_discharge_power": 3500,
            }
        ],
        defaults={},
    )

    assert _power_maxes(schema) == {
        "battery_1__max_charge_power_w": 2500,
        "battery_1__max_discharge_power_w": 2500,
    }
