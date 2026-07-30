"""Regression tests for Active Cell Balance measurement quality."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.omnibattery.control import active_balance_mode
from custom_components.omnibattery.control.active_balance_mode import (
    ActiveBalanceModeManager,
)
from custom_components.omnibattery.tracking.balance_monitor import BalanceMonitor


class _Coordinator:
    """Small hashable coordinator double for per-battery manager dictionaries."""

    def __init__(self) -> None:
        self.name = "Marstek Venus 2"
        self.data = {
            "battery_power": -7,
            "inverter_state": 1,
            "force_mode": 0,
            "set_charge_power": 0,
            "battery_soc": 96,
        }
        self._ab_charge_cmd_active = True
        self.active_balance_mode_phase = "CHARGE"


def _manager() -> ActiveBalanceModeManager:
    manager = ActiveBalanceModeManager.__new__(ActiveBalanceModeManager)
    manager._active_balance_charge_leg_started = {}
    manager._active_balance_charge_seen_power = {}
    manager._active_balance_charge_reject_counts = {}
    return manager


def test_new_charge_leg_ignores_residual_zero_power_during_engage_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DISCHARGE -> Standby residual power must not look like BMS rejection."""
    manager = _manager()
    coordinator = _Coordinator()
    clock = {"now": 100.0}
    monkeypatch.setattr(
        active_balance_mode.time, "monotonic", lambda: clock["now"]
    )

    for elapsed in (0, 2, 4, 8):
        clock["now"] = 100.0 + elapsed
        assert (
            manager._active_balance_charge_rejected_detected(
                coordinator, "CHARGE"
            )
            is False
        )

    clock["now"] = 110.0
    assert (
        manager._active_balance_charge_rejected_detected(coordinator, "CHARGE")
        is True
    )


def test_charge_acceptance_allows_later_cutoff_detection_inside_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once charge has flowed, a later 0 W sample may count as a real cutoff."""
    manager = _manager()
    coordinator = _Coordinator()
    clock = {"now": 100.0}
    monkeypatch.setattr(
        active_balance_mode.time, "monotonic", lambda: clock["now"]
    )

    coordinator.data["battery_power"] = 50
    assert (
        manager._active_balance_charge_rejected_detected(coordinator, "CHARGE")
        is False
    )

    coordinator.data["battery_power"] = 0
    clock["now"] = 102.0
    assert (
        manager._active_balance_charge_rejected_detected(coordinator, "CHARGE")
        is True
    )


def test_leaving_charge_resets_engage_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every charge leg must receive its own engage grace."""
    manager = _manager()
    coordinator = _Coordinator()
    monkeypatch.setattr(active_balance_mode.time, "monotonic", lambda: 100.0)

    manager._active_balance_charge_rejected_detected(coordinator, "CHARGE")
    assert coordinator in manager._active_balance_charge_leg_started

    assert (
        manager._active_balance_charge_rejected_detected(
            coordinator, "DISCHARGE"
        )
        is False
    )
    assert coordinator not in manager._active_balance_charge_leg_started
    assert coordinator not in manager._active_balance_charge_seen_power


async def test_below_stop_cutoff_stays_diagnostic_only() -> None:
    """A retry cutoff must not update the official Cell Delta series."""
    manager = _manager()
    monitor = SimpleNamespace(
        async_record_active_balance_measurement=AsyncMock()
    )
    manager._controller = SimpleNamespace(
        _balance_monitor=monitor,
        _persist_battery_runtime_config=Mock(),
    )
    coordinator = _Coordinator()
    details = {
        "delta_V": 0.093,
        "max_cell_voltage": 3.491,
        "min_cell_voltage": 3.398,
    }

    await manager._record_active_balance_mode_measurement(
        coordinator,
        details,
        source="bms_cut_below_stop",
    )

    monitor.async_record_active_balance_measurement.assert_not_awaited()
    persisted = manager._controller._persist_battery_runtime_config.call_args.args[1]
    assert persisted["active_balance_mode_last_cutoff_source"] == "bms_cut_below_stop"


async def test_wait_measure_updates_official_cell_delta_series() -> None:
    """The settled top measurement remains the source for balance entities."""
    manager = _manager()
    monitor = SimpleNamespace(
        async_record_active_balance_measurement=AsyncMock()
    )
    manager._controller = SimpleNamespace(
        _balance_monitor=monitor,
        _persist_battery_runtime_config=Mock(),
    )
    coordinator = _Coordinator()
    coordinator.active_balance_mode_phase = "WAIT_MEASURE"

    await manager._record_active_balance_mode_measurement(
        coordinator,
        {
            "delta_V": 0.165,
            "max_cell_voltage": 3.585,
            "min_cell_voltage": 3.420,
        },
    )

    monitor.async_record_active_balance_measurement.assert_awaited_once_with(
        coordinator,
        3.585,
        3.420,
        96,
        "WAIT_MEASURE",
    )


def test_balance_restore_average_and_history_ignore_charge_phase_glitches() -> None:
    """Stored 90 mV retry readings must not contaminate the official series."""
    host = "battery"
    monitor = BalanceMonitor.__new__(BalanceMonitor)
    monitor._data = {
        host: {
            "readings": [
                {"ts": "1", "delta_mV": 171.0, "type": "top_balance_measurement"},
                {
                    "ts": "2",
                    "delta_mV": 169.0,
                    "type": "active_balance_measurement",
                    "phase": "WAIT_MEASURE",
                },
                {
                    "ts": "3",
                    "delta_mV": 93.0,
                    "type": "active_balance_measurement",
                    "phase": "CHARGE",
                },
                {"ts": "4", "delta_mV": 167.0, "type": "top_balance_measurement"},
                {
                    "ts": "5",
                    "delta_mV": 95.0,
                    "type": "active_balance_transition",
                },
                {
                    "ts": "6",
                    "delta_mV": 165.0,
                    "type": "active_balance_measurement",
                    "phase": "WAIT_MEASURE",
                },
            ]
        }
    }

    recent = monitor.get_recent_readings(host)
    assert [reading["delta_mV"] for reading in recent] == [
        171.0,
        169.0,
        167.0,
        165.0,
    ]

    restored = monitor.get_initial_state(host)
    assert restored["delta_mV"] == 165.0
    assert restored["avg_4w"] == 168.0
