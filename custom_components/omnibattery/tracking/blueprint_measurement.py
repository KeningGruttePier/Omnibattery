"""Public event bridge from the active-balance blueprint to Omnibattery."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr

from ..const import DOMAIN, EVENT_BLUEPRINT_BALANCE_MEASUREMENT_READY
from .balance_monitor import BalanceMonitor

_LOGGER = logging.getLogger(__name__)


def _coordinator_for_device(
    hass: HomeAssistant,
    coordinators: Iterable[Any],
    device_id: str | None,
) -> Any | None:
    """Resolve a blueprint device-selector ID to its integration coordinator."""
    if not isinstance(device_id, str) or not device_id:
        return None

    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None

    identifiers = getattr(device, "identifiers", set())
    for coordinator in coordinators:
        if (DOMAIN, coordinator.device_key) in identifiers:
            return coordinator
    return None


def async_register_blueprint_balance_measurement_listener(
    hass: HomeAssistant,
    coordinators: Iterable[Any],
    balance_monitor: BalanceMonitor,
) -> Callable[[], None]:
    """Listen for settled measurements emitted by an active-balance blueprint."""

    async def _handle(event: Event) -> None:
        event_data = event.data
        coordinator = _coordinator_for_device(
            hass,
            coordinators,
            event_data.get("device_id"),
        )
        if coordinator is None:
            _LOGGER.debug(
                "Ignoring blueprint balance measurement for unknown device %s",
                event_data.get("device_id"),
            )
            return

        await balance_monitor.async_record_blueprint_balance_measurement(
            coordinator,
            phase=event_data.get("phase"),
            measurement_id=event_data.get("measurement_id"),
        )

    return hass.bus.async_listen(
        EVENT_BLUEPRINT_BALANCE_MEASUREMENT_READY,
        _handle,
    )
