"""Tests for system-level binary sensor diagnostics."""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.omnibattery.binary_sensor import CurtailmentStatusSensor
from custom_components.omnibattery.pricing import CurtailmentPlan


def _sensor(*, runtime_status: str, plan: CurtailmentPlan | None):
    controller = SimpleNamespace(
        smart_predischarge_enabled=True,
        _curtailment_runtime_status=runtime_status,
        _curtailment_runtime_reason="test",
        _curtailment_active_export_target_w=0.0,
        negative_injection_threshold=0.0,
        _curtailment_plan=plan,
    )
    return CurtailmentStatusSensor(None, None, controller)


def test_curtailment_attributes_expose_external_inverter_signal():
    plan = CurtailmentPlan(
        status="shortfall",
        reason="insufficient_pre_discharge_power_or_slots",
        required_headroom_kwh=4.0,
        current_headroom_kwh=2.5,
        shortfall_kwh=1.5,
    )

    attrs = _sensor(runtime_status="protected_window", plan=plan).extra_state_attributes

    assert attrs["protected_window_active"] is True
    assert attrs["headroom_deficit_kwh"] == 1.5
    assert attrs["inverter_curtailment_required"] is True


def test_curtailment_signal_is_unknown_without_safe_plan():
    attrs = _sensor(runtime_status="fail_safe", plan=None).extra_state_attributes

    assert attrs["protected_window_active"] is False
    assert attrs["inverter_curtailment_required"] is None
