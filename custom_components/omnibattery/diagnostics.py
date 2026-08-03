"""Diagnostics for Omnibattery config entries.

Home Assistant calls :func:`async_get_config_entry_diagnostics` when the user
presses *Download diagnostics* on the integration. It returns a JSON-serialisable
dump of connection health, driver traits and non-responsive-tracker state
(everything that otherwise lives only in transient logs), with host/serial and
sensor entity ids redacted.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Identifiers and user sensor references that could deanonymise the dump.
# async_redact_data recurses into nested dicts/lists, so per-battery "host"
# entries inside a batteries list are covered too.
TO_REDACT = {
    "host",
    "username",
    "password",
    "serial",
    "serial_port",
    "ip_address",
    "mac",
    "consumption_sensor",
    "grid_sensor",
    "solar_forecast_sensor",
    "average_price_sensor",
    "phase_1_power_sensor",
    "phase_2_power_sensor",
    "phase_3_power_sensor",
}


def _driver_info(coordinator) -> dict[str, Any]:
    """Static driver traits (no host/serial, which are identifiers)."""
    driver = coordinator.driver
    caps = coordinator.capabilities
    return {
        "connected": driver.connected,
        "model_label": driver.model_label,
        "capabilities": asdict(caps) if is_dataclass(caps) else str(caps),
    }


def _tracker_info(controller, coordinator) -> dict[str, Any]:
    """Non-responsive exclusion state for one battery (side-effect free)."""
    tracker = getattr(controller, "_non_responsive", None)
    if tracker is None:
        return {}
    info = tracker.batteries.get(coordinator, {})
    return {
        # excluded_names() reads without mutating; is_excluded() would reset the
        # fail counter on cooldown expiry, which a read-only dump must not do.
        "excluded": coordinator.name in tracker.excluded_names(),
        "fail_count": info.get("fail_count", 0),
        "reason": info.get("reason"),
        "retry_attempted": info.get("retry_attempted", False),
        "wake_used": info.get("wake_used", False),
    }


def _dynamic_pricing_info(controller) -> dict[str, Any]:
    """Return JSON-safe typed calendar diagnostics."""
    if controller is None:
        return {}
    schedule = getattr(controller, "_dynamic_pricing_schedule", None)
    info = {
        "negative_price_charging_enabled": getattr(
            controller, "negative_price_charging_enabled", False
        ),
        "active_slot_purpose": getattr(
            controller, "_active_dynamic_slot_purpose", None
        ),
    }
    if schedule is None:
        info["schedule_type"] = None
        info["selected_slots"] = []
        return info
    info.update(
        {
            "schedule_type": getattr(schedule, "schedule_type", "deficit"),
            "deficit_charging_needed": getattr(
                schedule, "deficit_charging_needed", schedule.charging_needed
            ),
            "negative_price_charging_needed": getattr(
                schedule, "negative_price_charging_needed", False
            ),
            "negative_price_energy_kwh": getattr(
                schedule, "negative_price_energy_kwh", 0.0
            ),
            "selected_slots": [
                {
                    "start": slot.start.isoformat(),
                    "end": slot.end.isoformat(),
                    "price": slot.price,
                    "purpose": (
                        schedule.purpose_for(slot)
                        if hasattr(schedule, "purpose_for")
                        else "deficit"
                    ),
                }
                for slot in schedule.selected_slots
            ],
        }
    )
    return info


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return a redacted health/driver/tracker dump for one config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = data.get("coordinators") or []
    controller = data.get("controller")

    batteries = [
        {
            "health": coord.health_snapshot(),
            "driver": _driver_info(coord),
            "tracker": _tracker_info(controller, coord),
        }
        for coord in coordinators
    ]

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "batteries": batteries,
        "dynamic_pricing": _dynamic_pricing_info(controller),
        "phase_protection": async_redact_data(
            controller._phase_power_limiter.diagnostics(), TO_REDACT
        )
        if controller is not None
        and getattr(controller, "_phase_power_limiter", None) is not None
        else {},
    }
