"""Regression tests for monotonic system daily-energy aggregates."""
from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.omnibattery.sensors import aggregate_sensors as aggregate_module
from custom_components.omnibattery.sensors.aggregate_sensors import (
    MarstekVenusAggregateSensor,
)
from tests.conftest import FakeCoordinator


def _set_now(monkeypatch, day: int) -> str:
    now = datetime(2026, 7, day, 12, 0)
    monkeypatch.setattr(aggregate_module.dt_util, "now", lambda: now)
    return now.date().isoformat()


def _coordinator(source_key: str, value: float, reset_date: str) -> FakeCoordinator:
    return FakeCoordinator(
        data={
            source_key: value,
            f"{source_key}_reset_date": reset_date,
        }
    )


def _sensor(
    aggregate_key: str,
    source_key: str,
    coordinators: list[FakeCoordinator],
    value: float | None,
    reset_date: str,
) -> MarstekVenusAggregateSensor:
    sensor = MarstekVenusAggregateSensor.__new__(MarstekVenusAggregateSensor)
    sensor.coordinators = coordinators
    sensor.definition = {"key": aggregate_key, "precision": 2}
    sensor._daily_source_key = source_key
    sensor._daily_value = value
    sensor._daily_reset_date = reset_date
    sensor.entity_id = f"sensor.{aggregate_key}"
    return sensor


@pytest.mark.parametrize(
    ("aggregate_key", "source_key"),
    (
        ("system_daily_charging_energy", "total_daily_charging_energy"),
        ("system_daily_discharging_energy", "total_daily_discharging_energy"),
    ),
)
def test_partial_restore_cannot_lower_system_daily_energy(
    monkeypatch, aggregate_key, source_key
):
    """A reload must retain the restored system value until every source is ready."""
    today = _set_now(monkeypatch, 28)
    coordinators = [
        _coordinator(source_key, 0.7, today),
        FakeCoordinator(data={}),
        _coordinator(source_key, 0.8, today),
    ]
    sensor = _sensor(aggregate_key, source_key, coordinators, 2.3, today)

    sensor._refresh_daily_value()

    assert sensor._daily_value == 2.3

    coordinators[1].data.update(
        {
            source_key: 1.0,
            f"{source_key}_reset_date": today,
        }
    )
    sensor._refresh_daily_value()

    assert sensor._daily_value == 2.5


@pytest.mark.parametrize(
    ("aggregate_key", "source_key"),
    (
        ("system_daily_charging_energy", "total_daily_charging_energy"),
        ("system_daily_discharging_energy", "total_daily_discharging_energy"),
    ),
)
def test_complete_same_day_decrease_is_rejected(
    monkeypatch, aggregate_key, source_key
):
    """Even a complete but stale/incorrect source set cannot create a reset."""
    today = _set_now(monkeypatch, 28)
    coordinators = [
        _coordinator(source_key, 0.2, today),
        _coordinator(source_key, 0.3, today),
        _coordinator(source_key, 0.2, today),
    ]
    sensor = _sensor(aggregate_key, source_key, coordinators, 2.3, today)

    sensor._refresh_daily_value()

    assert sensor._daily_value == 2.3


@pytest.mark.parametrize(
    ("aggregate_key", "source_key"),
    (
        ("system_daily_charging_energy", "total_daily_charging_energy"),
        ("system_daily_discharging_energy", "total_daily_discharging_energy"),
    ),
)
def test_local_day_change_allows_reset_then_waits_for_current_day_sources(
    monkeypatch, aggregate_key, source_key
):
    yesterday = _set_now(monkeypatch, 28)
    coordinators = [
        _coordinator(source_key, 1.0, yesterday),
        _coordinator(source_key, 1.3, yesterday),
    ]
    sensor = _sensor(aggregate_key, source_key, coordinators, 2.3, yesterday)

    today = _set_now(monkeypatch, 29)
    sensor._refresh_daily_value()

    assert sensor._daily_value == 0.0

    coordinators[0].data.update(
        {source_key: 0.1, f"{source_key}_reset_date": today}
    )
    sensor._refresh_daily_value()
    assert sensor._daily_value == 0.0

    coordinators[1].data.update(
        {source_key: 0.2, f"{source_key}_reset_date": today}
    )
    sensor._refresh_daily_value()

    assert sensor._daily_value == pytest.approx(0.3)
