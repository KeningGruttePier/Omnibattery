"""MQTT driver for the Hoymiles MS-A2 home battery.

The S-Miles Home MQTT service publishes Home Assistant discovery-style topics to
the broker already configured in HA.  This driver deliberately uses HA's MQTT
APIs; it never creates a second broker connection or stores broker credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .base import BatteryDriver, DriverCapabilities, ReadGroup, SetpointResult, TelemetrySnapshot

_LOGGER = logging.getLogger(__name__)
_DEFAULT_MAX_POWER_W = 1000
_ABSOLUTE_MAX_POWER_W = 2000
_KEEPALIVE_S = 50

SENSOR_DEFINITIONS: list[dict] = [
    {"key": "battery_soc", "name": "Battery SOC", "unit": "%", "device_class": "battery", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "high", "enabled_by_default": True},
    {"key": "battery_power", "name": "Battery Power", "unit": "W", "device_class": "power", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "high", "enabled_by_default": True},
    {"key": "battery_voltage", "name": "Battery Voltage", "unit": "V", "device_class": "voltage", "state_class": "measurement", "scale": 1, "precision": 1, "scan_interval": "medium", "enabled_by_default": True},
    {"key": "battery_current", "name": "Battery Current", "unit": "A", "device_class": "current", "state_class": "measurement", "scale": 1, "precision": 1, "scan_interval": "medium", "enabled_by_default": True},
    {"key": "internal_temperature", "name": "Internal Temperature", "unit": "°C", "device_class": "temperature", "state_class": "measurement", "scale": 1, "precision": 1, "scan_interval": "medium", "enabled_by_default": True},
    {"key": "wifi_signal_strength", "name": "WiFi Signal Strength", "unit": "dBm", "device_class": "signal_strength", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "low", "enabled_by_default": True},
    {"key": "inverter_state", "name": "Inverter State", "unit": None, "device_class": None, "state_class": None, "scale": 1, "precision": 0, "icon": "mdi:state-machine", "scan_interval": "high", "enabled_by_default": True, "states": {1: "Standby", 2: "Charge", 3: "Discharge"}},
    {"key": "pack_count", "name": "Pack Count", "unit": None, "device_class": None, "state_class": "measurement", "scale": 1, "precision": 0, "icon": "mdi:battery", "scan_interval": "low", "enabled_by_default": True},
    {"key": "total_daily_charging_energy", "name": "Total Daily Charging Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "scale": 0.001, "precision": 3, "scan_interval": "low", "enabled_by_default": True},
    {"key": "total_daily_discharging_energy", "name": "Total Daily Discharging Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "scale": 0.001, "precision": 3, "scan_interval": "low", "enabled_by_default": True},
]


class HoymilesMqttDriver(BatteryDriver):
    """Push telemetry and external-power control for one MS-A2 master."""

    def __init__(self, hass: HomeAssistant, device_id: str, *, max_charge_power_w: int = _DEFAULT_MAX_POWER_W,
                 max_discharge_power_w: int = _DEFAULT_MAX_POWER_W) -> None:
        self.hass = hass
        self.device_id = device_id
        self._max_charge_w = min(_ABSOLUTE_MAX_POWER_W, max(0, int(max_charge_power_w or _DEFAULT_MAX_POWER_W)))
        self._max_discharge_w = min(_ABSOLUTE_MAX_POWER_W, max(0, int(max_discharge_power_w or _DEFAULT_MAX_POWER_W)))
        self._capabilities = DriverCapabilities(False, False, True, self._max_charge_w, self._max_discharge_w,
            False, False, False, has_energy_counters=True, has_daily_energy_counters=True,
            has_nominal_capacity=False, setpoint_confirm_reliable=False, actuator_latency_s=1.8)
        self._cache: dict[str, Any] = {}
        self._connected = False
        self._shutting_down = False
        self._unsubscribers: list[Callable[[], Any]] = []
        self._write_lock = asyncio.Lock()
        self._keepalive_task: asyncio.Task | None = None
        self._last_net_power_w: int | None = None
        self._keepalive_offset = False
        self._last_wire_power: float | None = None
        self._read_groups = [ReadGroup("high", tuple(d["key"] for d in SENSOR_DEFINITIONS))]

    @property
    def capabilities(self): return self._capabilities
    @property
    def model_label(self): return "MS-A2"
    @property
    def serial(self): return self.device_id
    @property
    def connected(self): return self._connected
    @property
    def read_groups(self): return self._read_groups
    @property
    def sensor_definitions(self): return SENSOR_DEFINITIONS
    @property
    def number_definitions(self): return []
    @property
    def select_definitions(self): return []
    @property
    def switch_definitions(self): return []
    @property
    def binary_sensor_definitions(self): return []
    @property
    def button_definitions(self): return []
    @property
    def all_definitions(self): return SENSOR_DEFINITIONS
    @property
    def control_dependency_keys(self): return frozenset({"battery_soc", "battery_power", "commanded_net_power"})

    def _topic(self, component: str, object_id: str, suffix: str) -> str:
        return f"homeassistant/{component}/{self.device_id}/{object_id}/{suffix}"

    @property
    def _quick_topic(self): return self._topic("sensor", "quick", "state")
    @property
    def _device_topic(self): return self._topic("sensor", "device", "state")
    @property
    def _system_topic(self): return self._topic("sensor", "system", "state")
    @property
    def _power_config_topic(self): return self._topic("number", "power_ctrl", "config")
    @property
    def _ems_command_topic(self): return self._topic("select", "ems_mode", "command")
    @property
    def _power_set_topic(self): return self._topic("number", "power_ctrl", "set")

    async def connect(self) -> bool:
        if self._connected:
            return True
        try:
            for topic, handler in ((self._quick_topic, self._handle_quick), (self._device_topic, self._handle_device),
                                   (self._system_topic, self._handle_system), (self._power_config_topic, self._handle_power_config)):
                unsubscribe = await mqtt.async_subscribe(self.hass, topic, handler, qos=1)
                self._unsubscribers.append(unsubscribe)
        except Exception as err:
            _LOGGER.debug("Unable to subscribe to Hoymiles MQTT topics: %s", err)
            await self._unsubscribe_all()
            return False
        self._connected = True
        return True

    async def _unsubscribe_all(self) -> None:
        for unsubscribe in self._unsubscribers:
            try:
                result = unsubscribe()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass
        self._unsubscribers.clear()

    async def close(self) -> None:
        task, self._keepalive_task = self._keepalive_task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._connected:
            try:
                async with self._write_lock:
                    await self._publish("mqtt_ctrl", 0)
                    await self._publish("general", None)
            except Exception:
                pass
        await self._unsubscribe_all()
        self._connected = False
        self._last_net_power_w = None

    def set_shutting_down(self, value: bool) -> None: self._shutting_down = value

    @staticmethod
    def _payload(message) -> dict | None:
        raw = getattr(message, "payload", message)
        if isinstance(raw, bytes): raw = raw.decode("utf-8", "replace")
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _number(data: dict, key: str):
        value = data.get(key)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @callback
    def _handle_quick(self, message) -> None:
        data = self._payload(message)
        if not data: return
        self._merge_battery(data)
        status = data.get("bat_sts")
        if isinstance(status, str):
            states = {"standby": 1, "charge": 2, "charging": 2, "discharge": 3, "discharging": 3}
            mapped = states.get(status.lower())
            if mapped is not None: self._cache["inverter_state"] = mapped

    @callback
    def _handle_device(self, message) -> None:
        data = self._payload(message)
        if not data: return
        self._merge_battery(data)
        for source, target in (("bat_v", "battery_voltage"), ("bat_i", "battery_current"),
                               ("bat_temp", "internal_temperature"), ("rssi", "wifi_signal_strength"),
                               ("pack_num", "pack_count")):
            value = self._number(data, source)
            if value is not None: self._cache[target] = value

    @callback
    def _handle_system(self, message) -> None:
        data = self._payload(message)
        if not data: return
        self._merge_battery(data)
        for source, target in (("chg_e", "total_daily_charging_energy"), ("dchg_e", "total_daily_discharging_energy")):
            value = self._number(data, source)
            if value is not None: self._cache[target] = value
        if "ems_mode" in data: self._cache["ems_mode"] = data["ems_mode"]

    @callback
    def _handle_power_config(self, message) -> None:
        data = self._payload(message)
        if not data: return
        minimum, maximum = self._number(data, "min"), self._number(data, "max")
        if maximum is None: return
        # MQTT discovery uses a signed wire envelope. Avoid ever inflating caps.
        self._max_charge_w = min(_ABSOLUTE_MAX_POWER_W, max(0, int(-minimum))) if minimum is not None and minimum < 0 else self._max_charge_w
        self._max_discharge_w = min(_ABSOLUTE_MAX_POWER_W, max(0, int(maximum)))
        self._capabilities = DriverCapabilities(False, False, True, self._max_charge_w, self._max_discharge_w,
            False, False, False, has_energy_counters=True, has_daily_energy_counters=True,
            has_nominal_capacity=False, setpoint_confirm_reliable=False, actuator_latency_s=1.8)

    def _merge_battery(self, data: dict) -> None:
        soc = self._number(data, "sys_soc")
        if soc is None: soc = self._number(data, "soc")
        power = self._number(data, "sys_bat_p")
        if power is None: power = self._number(data, "bat_p")
        if soc is not None: self._cache["battery_soc"] = soc
        if power is not None: self._cache["battery_power"] = -power

    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        data = dict(self._cache)
        return data if keys is None else {key: data[key] for key in keys if key in data}

    def _clamp(self, net_power_w: int) -> int:
        return max(-self._max_discharge_w, min(self._max_charge_w, int(round(net_power_w))))

    def _wire_for(self, net_power_w: int, *, refresh: bool = False) -> float:
        wire = float(-net_power_w)
        if refresh and self._last_wire_power is not None:
            # Alternate from the last payload, not from the logical target. At
            # an envelope edge this yields e.g. -1000.0/-999.9 rather than
            # repeatedly choosing the same inward value.
            offset = -0.1 if self._keepalive_offset else 0.1
            candidate = self._last_wire_power + offset
            if -self._max_charge_w <= candidate <= self._max_discharge_w:
                wire = candidate
                self._keepalive_offset = not self._keepalive_offset
            else:
                wire = self._last_wire_power - offset
        return wire

    async def _publish(self, mode: str, wire_power: float | None) -> None:
        await mqtt.async_publish(self.hass, self._ems_command_topic, mode, qos=1, retain=False)
        if wire_power is not None:
            payload = f"{wire_power:.1f}" if wire_power % 1 else str(int(wire_power))
            await mqtt.async_publish(self.hass, self._power_set_topic, payload, qos=1, retain=False)

    async def apply_setpoint(self, net_power_w: int, *, mode_hint: Optional[str] = None, read_back: bool = True) -> SetpointResult:
        if not self._connected:
            return SetpointResult(False, 0, False, failure_reason="not_connected")
        applied = self._clamp(net_power_w)
        try:
            async with self._write_lock:
                wire = self._wire_for(applied)
                await self._publish("mqtt_ctrl", wire)
                self._last_wire_power, self._last_net_power_w = wire, applied
                self._keepalive_offset = False
                self._cache["commanded_net_power"] = applied
        except Exception as err:
            _LOGGER.debug("Hoymiles MQTT command failed: %s", err)
            return SetpointResult(False, applied, False, failure_reason="write_failed")
        self._ensure_keepalive()
        return SetpointResult(True, applied, False, battery_power_w=self._cache.get("battery_power"),
            applied={"commanded_net_power": applied})

    def _ensure_keepalive(self) -> None:
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = self.hass.async_create_task(self._keepalive_loop())

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_KEEPALIVE_S)
                await self._refresh_command()
        except asyncio.CancelledError:
            raise

    async def _refresh_command(self) -> bool:
        if not self._connected or self._last_net_power_w is None:
            return False
        try:
            async with self._write_lock:
                wire = self._wire_for(self._last_net_power_w, refresh=True)
                await self._publish("mqtt_ctrl", wire)
                self._last_wire_power = wire
            return True
        except Exception as err:
            _LOGGER.debug("Hoymiles MQTT keepalive failed: %s", err)
            return False

    async def standby(self) -> bool:
        if not self._connected: return False
        try:
            async with self._write_lock:
                await self._publish("mqtt_ctrl", 0)
                self._last_net_power_w = 0
                self._last_wire_power = 0
                self._cache["commanded_net_power"] = 0
            self._ensure_keepalive()
            return True
        except Exception:
            return False

    async def apply_config(self, **kwargs) -> bool: return True
    async def set_charge_cutoff(self, soc_pct: float) -> bool: return False
    async def set_rs485_control(self, enabled: bool) -> bool: return False
    async def write_control(self, key: str, value: int) -> bool: return False
    def net_power_from_data(self, data: dict) -> Optional[int]:
        value = data.get("commanded_net_power")
        return int(value) if isinstance(value, (int, float)) else None

    @classmethod
    async def probe(cls, hass: HomeAssistant, device_id: str, timeout: float = 5.0) -> tuple[bool, dict]:
        """Wait briefly for retained/live quick telemetry and clean up always."""
        event = asyncio.Event()
        metadata: dict[str, Any] = {}
        valid = False

        @callback
        def quick(message) -> None:
            nonlocal valid
            data = cls._payload(message)
            if data and (cls._number(data, "sys_soc") is not None or cls._number(data, "soc") is not None) and (cls._number(data, "sys_bat_p") is not None or cls._number(data, "bat_p") is not None):
                valid = True; event.set()

        @callback
        def config(message) -> None:
            data = cls._payload(message) or {}
            lo, hi = cls._number(data, "min"), cls._number(data, "max")
            if lo is not None and lo < 0: metadata["device_max_charge_power"] = min(_ABSOLUTE_MAX_POWER_W, int(-lo))
            if hi is not None and hi > 0: metadata["device_max_discharge_power"] = min(_ABSOLUTE_MAX_POWER_W, int(hi))

        unsubs = []
        try:
            unsubs.append(await mqtt.async_subscribe(hass, f"homeassistant/sensor/{device_id}/quick/state", quick, qos=1))
            unsubs.append(await mqtt.async_subscribe(hass, f"homeassistant/number/{device_id}/power_ctrl/config", config, qos=1))
            await asyncio.wait_for(event.wait(), timeout)
            return valid, metadata
        except Exception:
            return False, metadata
        finally:
            for unsubscribe in unsubs:
                try:
                    result = unsubscribe()
                    if hasattr(result, "__await__"): await result
                except Exception:
                    pass
