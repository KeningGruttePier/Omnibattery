"""Hoymiles MS-A2 MQTT driver contract tests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.omnibattery.drivers.hoymiles import HoymilesMqttDriver
from custom_components.omnibattery.config_flow import MarstekVenusConfigFlow


class _Mqtt:
    def __init__(self):
        self.callbacks = {}
        self.published = []
        self.unsubscribed = []
        self.fail_publish = False

    async def subscribe(self, hass, topic, callback, qos=0):
        self.callbacks[topic] = callback
        return lambda: self.unsubscribed.append(topic)

    async def publish(self, hass, topic, payload, qos=0, retain=False):
        if self.fail_publish:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, payload, qos, retain))


@pytest.fixture
def mqtt_mock(monkeypatch):
    fake = _Mqtt()
    monkeypatch.setattr("custom_components.omnibattery.drivers.hoymiles.mqtt.async_subscribe", fake.subscribe)
    monkeypatch.setattr("custom_components.omnibattery.drivers.hoymiles.mqtt.async_publish", fake.publish)
    return fake


@pytest.mark.asyncio
async def test_mqtt_telemetry_uses_aggregate_values_and_inverts_wire_sign(mqtt_mock):
    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    driver = HoymilesMqttDriver(hass, "MSA-1")
    assert await driver.connect()
    assert "homeassistant/sensor/MSA-1/quick/state" in mqtt_mock.callbacks
    mqtt_mock.callbacks[driver._quick_topic](SimpleNamespace(payload='{"soc": 20, "bat_p": -80, "sys_soc": 50, "sys_bat_p": 300, "bat_sts":"discharge"}'))
    mqtt_mock.callbacks[driver._device_topic](SimpleNamespace(payload='{"bat_v":51.2,"bat_i":2,"bat_temp":24,"rssi":-62,"pack_num":2}'))
    mqtt_mock.callbacks[driver._system_topic](SimpleNamespace(payload='{"chg_e":1240,"dchg_e":530}'))
    mqtt_mock.callbacks[driver._power_config_topic](SimpleNamespace(payload='{"min":-1800,"max":1800}'))
    snapshot = await driver.read_telemetry(["battery_soc", "battery_power", "inverter_state", "battery_voltage", "total_daily_charging_energy"])
    assert snapshot == {"battery_soc": 50, "battery_power": -300, "inverter_state": 3, "battery_voltage": 51.2, "total_daily_charging_energy": 1240}
    assert next(d for d in driver.sensor_definitions if d["key"] == "total_daily_charging_energy")["scale"] == 0.001
    assert driver.capabilities.max_charge_power_w == driver.capabilities.max_discharge_power_w == 1800
    mqtt_mock.callbacks[driver._quick_topic](SimpleNamespace(payload="not json"))
    assert (await driver.read_telemetry())["battery_soc"] == 50
    await driver.close()


@pytest.mark.asyncio
async def test_quick_fallback_uses_battery_values_and_inverts_charge_sign(mqtt_mock):
    driver = HoymilesMqttDriver(SimpleNamespace(async_create_task=asyncio.create_task), "MSA-1")
    await driver.connect()
    mqtt_mock.callbacks[driver._quick_topic](SimpleNamespace(payload='{"soc": 43, "bat_p": -250, "bat_sts": "charge"}'))
    assert await driver.read_telemetry(["battery_soc", "battery_power", "inverter_state"]) == {
        "battery_soc": 43, "battery_power": 250, "inverter_state": 2,
    }
    await driver.close()


@pytest.mark.asyncio
async def test_setpoint_clamps_inverts_and_close_restores_general(mqtt_mock):
    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    driver = HoymilesMqttDriver(hass, "MSA-1", max_charge_power_w=800, max_discharge_power_w=700)
    await driver.connect()
    result = await driver.apply_setpoint(900, read_back=False)
    assert result.ok and result.net_power_w == 800 and result.confirmed is False
    assert mqtt_mock.published[-1] == (driver._power_set_topic, "-800", 1, False)
    assert driver.net_power_from_data(result.applied) == 800
    await driver._refresh_command()
    assert mqtt_mock.published[-1][1] in ("-799.9", "-800")
    await driver.close()
    assert mqtt_mock.published[-3:] == [
        (driver._ems_command_topic, "mqtt_ctrl", 1, False),
        (driver._power_set_topic, "0", 1, False),
        (driver._ems_command_topic, "general", 1, False),
    ][-3:]
    assert len(mqtt_mock.unsubscribed) == 4


@pytest.mark.asyncio
async def test_setpoint_publish_failure_and_keepalive_alternation_at_both_limits(mqtt_mock):
    driver = HoymilesMqttDriver(SimpleNamespace(async_create_task=asyncio.create_task), "MSA-1", max_charge_power_w=800, max_discharge_power_w=700)
    await driver.connect()
    mqtt_mock.fail_publish = True
    failed = await driver.apply_setpoint(100, read_back=False)
    assert not failed.ok and failed.failure_reason == "write_failed"
    mqtt_mock.fail_publish = False

    await driver.apply_setpoint(800, read_back=False)
    await driver._refresh_command()
    first = mqtt_mock.published[-1][1]
    await driver._refresh_command()
    second = mqtt_mock.published[-1][1]
    assert {first, second} == {"-800", "-799.9"}

    await driver.apply_setpoint(-700, read_back=False)
    await driver._refresh_command()
    first = mqtt_mock.published[-1][1]
    await driver._refresh_command()
    second = mqtt_mock.published[-1][1]
    assert {first, second} == {"700", "699.9"}
    assert driver._last_net_power_w == -700
    await driver.close()


@pytest.mark.asyncio
async def test_probe_accepts_quick_telemetry_and_cleans_up(mqtt_mock):
    hass = SimpleNamespace()
    probe = asyncio.create_task(HoymilesMqttDriver.probe(hass, "MSA-1", timeout=0.2))
    await asyncio.sleep(0)
    mqtt_mock.callbacks["homeassistant/sensor/MSA-1/quick/state"](SimpleNamespace(payload='{"soc":50,"bat_p":-100}'))
    ok, metadata = await probe
    assert ok and metadata == {}
    assert len(mqtt_mock.unsubscribed) == 2


@pytest.mark.asyncio
async def test_probe_timeout_cleans_up_and_caps_paired_system_metadata(mqtt_mock):
    hass = SimpleNamespace()
    timeout = await HoymilesMqttDriver.probe(hass, "MSA-timeout", timeout=0.001)
    assert timeout == (False, {})
    assert len(mqtt_mock.unsubscribed) == 2

    probe = asyncio.create_task(HoymilesMqttDriver.probe(hass, "MSA-paired", timeout=0.2))
    await asyncio.sleep(0)
    mqtt_mock.callbacks["homeassistant/number/MSA-paired/power_ctrl/config"](SimpleNamespace(payload='{"min": -2500, "max": 2500}'))
    mqtt_mock.callbacks["homeassistant/sensor/MSA-paired/quick/state"](SimpleNamespace(payload='{"soc":50,"bat_p":-100}'))
    assert await probe == (True, {"device_max_charge_power": 2000, "device_max_discharge_power": 2000})


@pytest.mark.asyncio
async def test_config_flow_offers_hoymiles_and_software_capacity_defaults(monkeypatch):
    flow = MarstekVenusConfigFlow()
    flow.config_data = {"num_batteries": 1}
    form = await flow.async_step_battery_brand()
    schema = next(iter(form["data_schema"].schema.values())).config["options"]
    assert {option["value"] for option in schema} >= {"hoymiles", "marstek"}

    flow._current_battery_data = {"brand": "hoymiles"}
    limits = await flow.async_step_battery_limits()
    fields = {marker.schema for marker in limits["data_schema"].schema}
    assert {"max_charge_power", "max_discharge_power", "battery_capacity_kwh"} <= fields

    routed = await flow.async_step_battery_brand({"brand": "hoymiles"})
    assert routed["step_id"] == "battery_connection_hoymiles"

    probe = AsyncMock(return_value=(True, {"device_max_charge_power": 1800, "device_max_discharge_power": 1800}))
    monkeypatch.setattr(HoymilesMqttDriver, "probe", probe)
    flow.hass = SimpleNamespace()
    saved = await flow.async_step_battery_connection_hoymiles({"name": "Paired MS-A2", "device_id": "MSA-paired"})
    assert saved["step_id"] == "battery_limits"
    assert flow._current_battery_data == {
        "brand": "hoymiles", "name": "Paired MS-A2", "host": "MSA-paired", "port": 0,
        "device_id": "MSA-paired", "device_max_charge_power": 1800, "device_max_discharge_power": 1800,
    }
    assert {marker.schema for marker in saved["data_schema"].schema} >= {"battery_capacity_kwh", "max_charge_power"}
    await flow.async_step_battery_limits({
        "max_charge_power": 1800, "max_discharge_power": 1800, "max_soc": 100, "min_soc": 10,
        "charge_hysteresis_percent": 2, "backup_offgrid_threshold": 50, "battery_capacity_kwh": 2.24,
    })
    assert flow.battery_configs[0]["battery_capacity_kwh"] == 2.24
