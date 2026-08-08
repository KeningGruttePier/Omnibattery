"""Characterization tests for PricingManager (module-8 PR3).

These pin the *current* behavior of the runtime pricing engine extracted from
``ChargeDischargeController`` so the move to ``pricing/engine.py`` is proven
cero-cambio-funcional. Runtime state stays on the controller by reference; the
manager reads/writes it via ``self._controller`` (matching the production wiring
where ``sensor.py`` / ``binary_sensor.py`` and the PD control loop also touch it).

No hardware, no running Home Assistant. ``PricingManager.__init__`` only stores
``hass``/``controller`` references, so it is built directly with a SimpleNamespace
hass and a stub controller. Tests cover the pure / early-return branches that need
no ``hass`` and no time mocking.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.omnibattery.const import (
    DEFAULT_ROUND_TRIP_EFFICIENCY,
    PRICE_INTEGRATION_CKW,
    PRICE_INTEGRATION_NORDPOOL,
    PRICE_INTEGRATION_TIBBER,
    PREDICTIVE_MODE_DYNAMIC_PRICING,
    PREDICTIVE_MODE_REALTIME_PRICE,
    PREDICTIVE_MODE_TIME_SLOT,
)
from custom_components.omnibattery.pricing import (
    BatterySnapshot,
    CurtailmentPlan,
    PreDischargeSlot,
    PriceSlot,
)
from custom_components.omnibattery.pricing import engine as pricing_engine
from custom_components.omnibattery.pricing.engine import PricingManager
from custom_components.omnibattery.pricing.nordpool import OfficialNordPoolSource
from custom_components.omnibattery.pricing.curtailment import (
    EXPORT_MODE_AUTOMATIC,
    EXPORT_MODE_CUSTOM,
    EXPORT_MODE_SELF_CONSUMPTION,
)


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------

def _controller(**overrides):
    """Stub controller exposing only the state/collaborators the manager reads.
    ``_removed`` / ``_set`` record discharge-block calls so tests can assert which
    branch of ``apply_price_discharge_block`` ran."""
    removed: list = []
    set_calls: list = []

    base = dict(
        # discharge-block recorders
        remove_discharge_block=lambda source: removed.append(source),
        set_discharge_block=lambda source, reason, details=None: set_calls.append(
            (source, reason, details)
        ),
        _price_based_discharge_blocked=False,
        # pricing state
        _dynamic_pricing_schedule=None,
        _dynamic_pricing_evaluated_date=None,
        _dp_evening_reevaluated_date=None,
        _dp_daily_avg_price=None,
        # config defaults (DP discharge-control path)
        predictive_charging_mode=PREDICTIVE_MODE_TIME_SLOT,
        dp_price_discharge_control=False,
        rt_price_discharge_control=False,
        price_sensor=None,
        price_integration_type=PRICE_INTEGRATION_NORDPOOL,
        max_price_threshold=None,
        discharge_price_threshold=None,
        min_arbitrage_margin=None,
        round_trip_efficiency=DEFAULT_ROUND_TRIP_EFFICIENCY,
        average_price_sensor=None,
    )
    base.update(overrides)
    ctrl = SimpleNamespace(**base)
    ctrl._removed = removed
    ctrl._set = set_calls
    return ctrl


def _mgr(ctrl):
    return PricingManager(SimpleNamespace(), ctrl)


def _schedule(slots):
    """Minimal schedule stand-in: only ``selected_slots`` is read here."""
    return SimpleNamespace(selected_slots=slots)


# ----------------------------------------------------------------------
# _get_price_unit
# ----------------------------------------------------------------------

def test_price_unit_ckw_is_chf():
    assert _mgr(_controller(price_integration_type=PRICE_INTEGRATION_CKW))._get_price_unit() == "CHF/kWh"


def test_price_unit_default_is_eur():
    assert _mgr(_controller(price_integration_type=PRICE_INTEGRATION_NORDPOOL))._get_price_unit() == "€/kWh"


def test_price_unit_uses_configured_nordpool_currency():
    state = SimpleNamespace(attributes={"unit_of_measurement": "SEK/kWh"})
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: state))
    ctrl = _controller(
        price_integration_type=PRICE_INTEGRATION_NORDPOOL,
        price_sensor="sensor.nord_pool_se3_current_price",
    )

    assert PricingManager(hass, ctrl)._get_price_unit() == "SEK/kWh"


def test_hacs_nordpool_current_price_and_unit_are_normalized_from_cents():
    state = SimpleNamespace(
        state="12.5",
        attributes={
            "price_in_cents": True,
            "unit": "kWh",
            "currency": "EUR",
            "unit_of_measurement": "c/kWh",
            "raw_today": [],
        },
    )
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: state))
    ctrl = _controller(
        price_integration_type=PRICE_INTEGRATION_NORDPOOL,
        price_sensor="sensor.nordpool_kwh_nl_eur",
    )
    manager = PricingManager(hass, ctrl)

    assert manager._get_current_price() == 0.125
    assert manager._get_price_unit() == "€/kWh"


# ----------------------------------------------------------------------
# is_in_dynamic_pricing_slot
# ----------------------------------------------------------------------

def test_in_slot_false_when_no_schedule():
    assert _mgr(_controller()).is_in_dynamic_pricing_slot() is False


def test_in_slot_true_when_now_inside_a_slot():
    now = datetime.now()
    slot = PriceSlot(start=now - timedelta(minutes=30), end=now + timedelta(minutes=30), price=0.1)
    ctrl = _controller(_dynamic_pricing_schedule=_schedule([slot]))
    assert _mgr(ctrl).is_in_dynamic_pricing_slot() is True


def test_in_slot_false_when_slot_in_the_past():
    now = datetime.now()
    slot = PriceSlot(start=now - timedelta(hours=2), end=now - timedelta(hours=1), price=0.1)
    ctrl = _controller(_dynamic_pricing_schedule=_schedule([slot]))
    assert _mgr(ctrl).is_in_dynamic_pricing_slot() is False


# ----------------------------------------------------------------------
# evaluation-time guards (deterministic "already done today" branch)
# ----------------------------------------------------------------------

def test_evening_reeval_false_when_already_done_today():
    ctrl = _controller(_dp_evening_reevaluated_date=datetime.now().date())
    assert _mgr(ctrl)._is_evening_reevaluation_time() is False


# ----------------------------------------------------------------------
# _is_dp_soc_drop_reeval (SOC-drop upward re-eval, #411)
# ----------------------------------------------------------------------

def _coord(soc):
    """Coordinator stand-in exposing only ``data['battery_soc']``."""
    return SimpleNamespace(data={"battery_soc": soc})


def test_soc_drop_reeval_false_when_no_reference():
    # Before the 00:05 eval sets a reference, the trigger never fires.
    ctrl = _controller(_dp_last_eval_soc=None, coordinators=[_coord(20)])
    assert _mgr(ctrl)._is_dp_soc_drop_reeval() is False


def test_soc_drop_reeval_true_on_large_drop():
    # Reporter's case: eval'd at 60%, woke to 24% → 36% drop ≥ 30% threshold.
    ctrl = _controller(_dp_last_eval_soc=60.0, coordinators=[_coord(24)])
    assert _mgr(ctrl)._is_dp_soc_drop_reeval() is True


def test_soc_drop_reeval_false_below_threshold():
    # 60 → 40 is a 20% drop, under the 30% threshold.
    ctrl = _controller(_dp_last_eval_soc=60.0, coordinators=[_coord(40)])
    assert _mgr(ctrl)._is_dp_soc_drop_reeval() is False


def test_soc_drop_reeval_false_on_soc_rise():
    # Directional: a rise (charged up) never triggers an upward re-plan.
    ctrl = _controller(_dp_last_eval_soc=30.0, coordinators=[_coord(70)])
    assert _mgr(ctrl)._is_dp_soc_drop_reeval() is False


def test_soc_drop_reeval_false_when_no_coordinator_data():
    ctrl = _controller(_dp_last_eval_soc=60.0, coordinators=[SimpleNamespace(data=None)])
    assert _mgr(ctrl)._is_dp_soc_drop_reeval() is False


# ----------------------------------------------------------------------
# _project_remaining_consumption (evening recharge deficit, #409)
# ----------------------------------------------------------------------

def test_remaining_consumption_projects_todays_rate():
    # 18:00, 12 kWh used so far → 0.667 kWh/h × 6h left = 4.0 kWh.
    remaining, rate = PricingManager._project_remaining_consumption(18.0, 12.0, 20.0)
    assert round(rate, 3) == 0.667
    assert round(remaining, 2) == 4.0


def test_remaining_consumption_heavy_day_charges_more_than_light():
    # Same hour: a heavy day so far projects a larger remaining need than a
    # light day — the property "avg − consumed" got backwards.
    heavy, _ = PricingManager._project_remaining_consumption(18.0, 18.0, 17.0)
    light, _ = PricingManager._project_remaining_consumption(18.0, 6.0, 17.0)
    assert heavy > light


def test_remaining_consumption_cold_accumulator_uses_avg_rate():
    # consumed_today = 0 (e.g. just after restart) → fall back to avg/24 rate.
    remaining, rate = PricingManager._project_remaining_consumption(18.0, 0.0, 24.0)
    assert rate == 1.0                  # 24 kWh / 24 h
    assert round(remaining, 2) == 6.0   # 1.0 × 6 h


def test_remaining_consumption_zero_at_midnight():
    remaining, _ = PricingManager._project_remaining_consumption(24.0, 20.0, 20.0)
    assert remaining == 0.0


# ----------------------------------------------------------------------
# _remaining_solar_today_kwh (evening/SOC-drop recharge, pre-dawn blind spot)
# ----------------------------------------------------------------------

def _solar_ctrl(forecast="40.0", produced=0.0, t_start=None):
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda eid: SimpleNamespace(state=forecast) if forecast is not None else None))
    ctrl = _controller(
        solar_forecast_sensor="sensor.solcast_today",
        _daily_solar_energy_kwh=produced,
        _solar_t_start=t_start,
        _consumption_tracker=SimpleNamespace(
            estimate_t_end=lambda: 21.0,
            get_solar_fraction_done=lambda now_h, t_start, t_end: 0.5,
        ),
    )
    return PricingManager(hass, ctrl)


def test_remaining_solar_predawn_uses_full_forecast():
    # #411 regression: SOC-drop re-eval fires pre-dawn (accumulator 0, no
    # T_start) → the whole forecast is still to come, not 0.
    assert _solar_ctrl()._remaining_solar_today_kwh(6.0) == 40.0 * 0.85


def test_remaining_solar_zero_when_no_production_after_fallback_hour():
    # Past T_START_FALLBACK_HOUR with nothing produced: solar sensor likely
    # broken — keep the conservative 0 so the evening top-up still books slots.
    assert _solar_ctrl()._remaining_solar_today_kwh(16.0) == 0.0


def test_remaining_solar_subtracts_produced_when_accumulator_warm():
    assert _solar_ctrl(produced=10.0)._remaining_solar_today_kwh(12.0) == 40.0 * 0.85 - 10.0


def test_remaining_solar_uses_fraction_when_t_start_known():
    # Accumulator cold but production started → sinusoidal fraction (stub: 50%).
    assert _solar_ctrl(t_start=8.0)._remaining_solar_today_kwh(14.0) == 40.0 * 0.85 * 0.5


def test_remaining_solar_zero_when_forecast_unavailable():
    assert _solar_ctrl(forecast="unavailable")._remaining_solar_today_kwh(6.0) == 0.0


def test_remaining_solar_zero_when_no_sensor_configured():
    ctrl = _controller(solar_forecast_sensor=None)
    assert PricingManager(SimpleNamespace(), ctrl)._remaining_solar_today_kwh(6.0) == 0.0


# ----------------------------------------------------------------------
# _evaluate_dynamic_pricing (discussion #87: schedule capped by headroom)
# ----------------------------------------------------------------------

def test_dynamic_pricing_sizes_slots_from_planned_charge_not_full_deficit():
    import asyncio

    async def should_charge():
        return {
            "should_charge": True,
            "avg_soc": 19.0,
            "avg_consumption_kwh": 4.552857,
            "energy_deficit_kwh": 4.552857,
            "planned_grid_charge_kwh": 1.5808,
        }

    async def no_op(*_args, **_kwargs):
        return None

    start = datetime.now() + timedelta(hours=1)
    slots = [
        PriceSlot(
            start=start + timedelta(minutes=15 * i),
            end=start + timedelta(minutes=15 * (i + 1)),
            price=0.30 - i / 1000,
        )
        for i in range(18)
    ]
    ctrl = _controller(
        _should_activate_grid_charging=should_charge,
        _last_decision_data=None,
        _dp_last_eval_soc=None,
        _dp_eval_retry_count=0,
        max_contracted_power=7000,
        max_charge_capacity=1200,
    )
    mgr = _mgr(ctrl)
    mgr._maybe_refresh_tibber_prices = no_op
    mgr._parse_price_data = lambda horizon_end=None: slots
    mgr._send_dynamic_pricing_notification = no_op

    asyncio.run(mgr._evaluate_dynamic_pricing())

    assert ctrl._dynamic_pricing_schedule.hours_needed == 2.0
    assert len(ctrl._dynamic_pricing_schedule.selected_slots) == 8


# ----------------------------------------------------------------------
# apply_price_discharge_block — early-return branches (no hass touched)
# ----------------------------------------------------------------------

def test_discharge_block_removed_when_mode_not_price():
    ctrl = _controller(predictive_charging_mode=PREDICTIVE_MODE_TIME_SLOT)
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]
    assert ctrl._set == []


def test_discharge_block_removed_when_dp_control_disabled():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=False,
        price_sensor="sensor.price",
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


def test_discharge_block_removed_when_dp_enabled_but_no_sensor():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=True,
        price_sensor=None,
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


def test_discharge_block_removed_when_rt_control_disabled():
    ctrl = _controller(
        predictive_charging_mode=PREDICTIVE_MODE_REALTIME_PRICE,
        rt_price_discharge_control=False,
        price_sensor="sensor.price",
    )
    _mgr(ctrl).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


# ----------------------------------------------------------------------
# apply_price_discharge_block — separate discharge floor / idle band (#408)
# ----------------------------------------------------------------------

def _mgr_with_price(ctrl, price):
    """PricingManager whose price sensor reads ``price`` (Nordpool float path)."""
    state = SimpleNamespace(state=str(price), attributes={})
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _eid: state))
    return PricingManager(hass, ctrl)


def _dp_band_controller(**overrides):
    base = dict(
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        dp_price_discharge_control=True,
        price_sensor="sensor.price",
        max_price_threshold=0.20,   # charge ceiling
        discharge_price_threshold=0.30,  # discharge floor
    )
    base.update(overrides)
    return _controller(**base)


def test_dp_discharge_floor_blocks_inside_idle_band():
    # price 0.25 sits in the idle band (ceiling 0.20 < 0.25 < floor 0.30):
    # discharge stays blocked. Single-threshold behavior would unblock at 0.21.
    ctrl = _dp_band_controller()
    _mgr_with_price(ctrl, 0.25).apply_price_discharge_block()
    assert ctrl._set and ctrl._set[0][0] == "price_discharge"
    assert ctrl._price_based_discharge_blocked is True


def test_dp_discharge_allowed_above_floor():
    ctrl = _dp_band_controller()
    _mgr_with_price(ctrl, 0.35).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]
    assert ctrl._price_based_discharge_blocked is False


def test_dp_discharge_floor_unset_falls_back_to_charge_ceiling():
    # Back-compat: no floor → reuse max_price_threshold (0.20) for both, so
    # price 0.25 > 0.20 unblocks discharge exactly as before #408.
    ctrl = _dp_band_controller(discharge_price_threshold=None)
    _mgr_with_price(ctrl, 0.25).apply_price_discharge_block()
    assert ctrl._removed == ["price_discharge"]


# ----------------------------------------------------------------------
# _maybe_refresh_tibber_prices (#21: default call only returns today)
# ----------------------------------------------------------------------

class _FakeTibberServices:
    """Records ``async_call`` args; ``get_prices`` always reports available."""

    def __init__(self):
        self.calls: list = []

    def has_service(self, domain, service):
        return domain == "tibber" and service == "get_prices"

    async def async_call(self, domain, service, data, blocking=True, return_response=True):
        self.calls.append(data)
        return {"prices": {}}


def test_tibber_refresh_requests_through_day_after_tomorrow():
    import asyncio
    from homeassistant.util import dt as dt_util

    services = _FakeTibberServices()
    hass = SimpleNamespace(services=services)
    ctrl = _controller(
        price_integration_type=PRICE_INTEGRATION_TIBBER,
        _tibber_price_slots=[],
        _tibber_prices_fetched_at=None,
    )

    asyncio.run(PricingManager(hass, ctrl)._maybe_refresh_tibber_prices(force=True))

    assert len(services.calls) == 1
    end = dt_util.parse_datetime(services.calls[0]["end"])
    assert end == dt_util.start_of_local_day() + timedelta(days=2)
    assert ctrl._price_based_discharge_blocked is False


# ----------------------------------------------------------------------
# Official Nord Pool service provider
# ----------------------------------------------------------------------

class _FakeNordPoolServices:
    """Records the official service request and returns one current-day area."""

    def __init__(self, response=None):
        self.calls: list = []
        self.response = response or {}

    def has_service(self, domain, service):
        return domain == "nordpool" and service == "get_prices_for_date"

    async def async_call(self, domain, service, data, blocking=True, return_response=True):
        self.calls.append((domain, service, data))
        return self.response


def test_official_nordpool_refresh_requests_today_and_selected_area(monkeypatch):
    import asyncio
    from homeassistant.util import dt as dt_util

    now = datetime.now()
    services = _FakeNordPoolServices(
        {
            "ES": [
                {
                    "start": (now - timedelta(minutes=15)).isoformat(),
                    "end": (now + timedelta(minutes=15)).isoformat(),
                    "price": 123.45,
                }
            ]
        }
    )
    hass = SimpleNamespace(
        services=services,
        states=SimpleNamespace(get=lambda _entity_id: SimpleNamespace(attributes={})),
    )
    source = [OfficialNordPoolSource("nordpool-entry", "ES")]
    monkeypatch.setattr(
        pricing_engine,
        "resolve_official_nordpool_source",
        lambda *_args: source[0],
    )
    ctrl = _controller(
        price_sensor="sensor.nord_pool_es_current_price",
        _nordpool_price_slots=[],
        _nordpool_prices_fetched_at=None,
    )
    manager = PricingManager(hass, ctrl)

    asyncio.run(manager._maybe_refresh_nordpool_prices(force=True))
    asyncio.run(manager._maybe_refresh_nordpool_prices())

    assert len(services.calls) == 1
    domain, service, data = services.calls[0]
    assert (domain, service) == ("nordpool", "get_prices_for_date")
    assert data == {
        "config_entry": "nordpool-entry",
        "date": dt_util.now().date(),
        "areas": ["ES"],
    }
    assert len(ctrl._nordpool_price_slots) == 1
    assert ctrl._nordpool_price_slots[0].price == 0.12345
    assert manager._get_current_price() == 0.12345

    # A hot-reload that selects another official market area must invalidate
    # the otherwise-fresh hourly cache immediately.
    source[0] = OfficialNordPoolSource("nordpool-entry", "FR")
    services.response = {
        "FR": [
            {
                "start": (now - timedelta(minutes=15)).isoformat(),
                "end": (now + timedelta(minutes=15)).isoformat(),
                "price": 200.0,
            }
        ]
    }
    asyncio.run(manager._maybe_refresh_nordpool_prices())

    assert len(services.calls) == 2
    assert services.calls[1][2]["areas"] == ["FR"]
    assert ctrl._nordpool_price_slots[0].price == 0.2


def test_hacs_nordpool_raw_today_does_not_call_official_service():
    import asyncio

    services = _FakeNordPoolServices()
    state = SimpleNamespace(
        state="0.10",
        attributes={
            "raw_today": [
                {
                    "start": datetime.now(),
                    "end": datetime.now() + timedelta(hours=1),
                    "value": 0.10,
                }
            ]
        },
    )
    hass = SimpleNamespace(
        services=services,
        states=SimpleNamespace(get=lambda _entity_id: state),
    )
    ctrl = _controller(
        price_sensor="sensor.nordpool_kwh_es_eur",
        _nordpool_price_slots=[],
        _nordpool_prices_fetched_at=None,
    )

    asyncio.run(PricingManager(hass, ctrl)._maybe_refresh_nordpool_prices(force=True))

    assert services.calls == []


# ----------------------------------------------------------------------
# Smart pre-discharge runtime lifecycle
# ----------------------------------------------------------------------

def test_smart_predischarge_is_scoped_to_predictive_dynamic_pricing():
    ctrl = _controller(
        smart_predischarge_enabled=True,
        predictive_charging_enabled=True,
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
    )
    manager = _mgr(ctrl)

    assert manager._smart_predischarge_enabled() is True

    ctrl.predictive_charging_mode = PREDICTIVE_MODE_REALTIME_PRICE
    assert manager._smart_predischarge_enabled() is False


def test_smart_predischarge_cleanup_removes_override_and_blockers():
    calls = []
    ctrl = _controller()
    ctrl.coordinators = []
    ctrl.remove_setpoint_override = lambda source: calls.append(("override", source))
    ctrl.remove_discharge_block = lambda source, coordinator=None: calls.append(
        ("block", source, coordinator)
    )
    ctrl._curtailment_plan = CurtailmentPlan(status="predischarging", reason="selected")
    manager = _mgr(ctrl)

    manager.clear_curtailment_runtime("disabled")

    assert ("override", "curtailment_predischarge") in calls
    assert ("block", "curtailment_negative_window", None) in calls
    assert ctrl._curtailment_runtime_status == "disabled"
    assert ctrl._curtailment_runtime_reason == "disabled"


def test_smart_predischarge_runtime_starts_stops_and_protects_negative_window():
    now = datetime.now()
    active_pre_slot = PreDischargeSlot(
        now - timedelta(minutes=1), now + timedelta(minutes=10), 0.40
    )
    future_risk = PriceSlot(
        now + timedelta(hours=1), now + timedelta(hours=2), -0.10
    )
    calls = []
    state = SimpleNamespace(state="0.0", attributes={})
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda _entity_id: state))
    coordinator = SimpleNamespace(data={"battery_soc": 80.0}, is_available=True, name="b1")
    ctrl = _controller(
        smart_predischarge_enabled=True,
        predictive_charging_enabled=True,
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        coordinators=[coordinator],
        consumption_sensor="sensor.grid",
        _curtailment_plan=CurtailmentPlan(
            status="planned",
            reason="headroom_required",
            risk_slots=[future_risk],
            selected_discharge_slots=[active_pre_slot],
            required_headroom_kwh=3.0,
        ),
        remove_setpoint_override=lambda source: calls.append(("remove_override", source)),
        set_setpoint_override=lambda source, value, priority=0: calls.append(
            ("set_override", source, value, priority)
        ),
        remove_discharge_block=lambda source, coordinator=None: calls.append(
            ("remove_block", source, coordinator)
        ),
        set_discharge_block=lambda source, reason, details=None, coordinator=None: calls.append(
            ("set_block", source, reason, coordinator)
        ),
        _apply_meter_transform=lambda _state: 0.0,
        _curtailment_active=False,
        _curtailment_active_export_target_w=0.0,
    )
    manager = PricingManager(hass, ctrl)
    manager._get_current_price = lambda: 0.30
    manager._curtailment_battery_snapshots = lambda: [
        BatterySnapshot("b1", 80.0, 10.0, 100.0, 10.0, 2000.0)
    ]

    manager.refresh_curtailment_runtime()

    assert any(call[:2] == ("set_override", "curtailment_predischarge") for call in calls)
    assert ctrl._curtailment_runtime_status == "predischarging"

    # The same runtime plan blocks normal discharge during the negative window.
    ctrl._curtailment_plan = CurtailmentPlan(
        status="planned",
        reason="headroom_required",
        risk_slots=[PriceSlot(now - timedelta(minutes=1), now + timedelta(minutes=10), -0.10)],
        selected_discharge_slots=[],
        required_headroom_kwh=3.0,
    )
    manager._get_current_price = lambda: -0.10
    manager.refresh_curtailment_runtime()

    assert ctrl._curtailment_runtime_status == "protected_window"
    assert any(call[0] == "set_block" and call[1] == "curtailment_negative_window" for call in calls)

    ctrl.smart_predischarge_enabled = False
    manager.refresh_curtailment_runtime()
    assert ctrl._curtailment_runtime_status == "disabled"
    assert ("remove_override", "curtailment_predischarge") in calls


def test_curtailment_runtime_releases_space_for_underproduction_and_stops_on_excess():
    now = datetime.now()
    risk = PriceSlot(now + timedelta(minutes=5), now + timedelta(hours=1), -0.10)
    plan = CurtailmentPlan(
        status="protected",
        reason="headroom_sufficient",
        risk_slots=[risk],
        required_headroom_kwh=3.0,
        solar_reserve_remaining_kwh=3.0,
        solar_reserve_by_slot={risk: 3.0},
        solar_forecast_by_slot={risk: 4.0},
        consumption_forecast_by_slot={risk: 0.0},
        headroom_margin_kwh=0.0,
        opportunistic_space_kwh=1.0,
    )
    plan.actual_solar_by_slot = {risk: 2.0}
    ctrl = _controller(
        smart_predischarge_enabled=True,
        predictive_charging_enabled=True,
        predictive_charging_mode=PREDICTIVE_MODE_DYNAMIC_PRICING,
        max_charge_capacity=4000.0,
        _curtailment_plan=plan,
    )
    manager = _mgr(ctrl)
    snapshots = [BatterySnapshot("b1", 60.0, 10.0, 100.0, 10.0, 2000.0)]

    manager._update_curtailment_opportunistic_diagnostics(plan, snapshots, now)
    assert plan.solar_reserve_remaining_kwh == pytest.approx(1.5)
    assert plan.opportunistic_space_kwh == pytest.approx(2.5)
    assert plan.opportunistic_charge_reason == "solar_underproduction_released_space"

    plan.actual_solar_by_slot = {risk: 6.0}
    manager._update_curtailment_opportunistic_diagnostics(plan, snapshots, now)
    assert plan.solar_reserve_remaining_kwh == pytest.approx(4.5)
    assert plan.opportunistic_space_kwh == 0.0
    assert plan.opportunistic_charge_reason == "solar_overproduction_reduced_space"


def test_curtailment_daily_solar_accumulator_releases_space_progressively():
    now = datetime.now()
    risk = PriceSlot(now + timedelta(minutes=5), now + timedelta(hours=1), -0.10)
    plan = CurtailmentPlan(
        status="protected",
        reason="headroom_sufficient",
        risk_slots=[risk],
        solar_forecast_kwh=4.0,
        solar_reserve_by_slot={risk: 3.0},
        solar_forecast_by_slot={risk: 4.0},
        consumption_forecast_by_slot={risk: 0.0},
    )
    manager = _solar_ctrl(forecast="4.0", produced=1.0, t_start=6.0)
    manager._controller._curtailment_plan = plan
    snapshots = [BatterySnapshot("b1", 60.0, 10.0, 100.0, 10.0, 2000.0)]

    manager._update_curtailment_opportunistic_diagnostics(plan, snapshots, now)

    # The fake tracker says 50% of the forecast should have arrived by now;
    # 1 kWh actual versus 2 kWh expected halves the remaining reserve.
    assert plan.solar_reserve_remaining_kwh == pytest.approx(1.5)
    assert plan.opportunistic_space_kwh == pytest.approx(2.5)
    assert plan.opportunistic_charge_reason == "solar_underproduction_released_space"


def test_curtailment_export_settings_keep_legacy_compatibility_and_modes():
    legacy_zero = _controller(predischarge_max_export_power_w=0.0)
    legacy_custom = _controller(predischarge_max_export_power_w=750.0)
    automatic = _controller(
        predischarge_export_mode=EXPORT_MODE_AUTOMATIC,
        predischarge_max_export_power_w=750.0,
    )
    custom = _controller(
        predischarge_export_mode=EXPORT_MODE_CUSTOM,
        predischarge_export_limit_w=900.0,
    )

    assert _mgr(legacy_zero)._curtailment_export_settings() == (
        EXPORT_MODE_SELF_CONSUMPTION,
        0.0,
    )
    assert _mgr(legacy_custom)._curtailment_export_settings() == (
        EXPORT_MODE_CUSTOM,
        750.0,
    )
    assert _mgr(automatic)._curtailment_export_settings() == (
        EXPORT_MODE_AUTOMATIC,
        0.0,
    )
    assert _mgr(custom)._curtailment_export_settings() == (
        EXPORT_MODE_CUSTOM,
        900.0,
    )
