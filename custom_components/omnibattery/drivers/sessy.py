"""Local HTTP driver for a Sessy home battery.

Sessy's dongle exposes a small local JSON API protected by the credentials
printed on the dongle. The controller uses the API power strategy and its signed
setpoint: Sessy uses positive values for generation/discharge, whereas
Omnibattery uses positive values for charging.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from .base import BatteryDriver, DriverCapabilities, ReadGroup, SetpointResult, TelemetrySnapshot

_LOGGER = logging.getLogger(__name__)
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_API_STRATEGY = "POWER_STRATEGY_API"
_MAX_CHARGE_POWER_W = 2200
_MAX_DISCHARGE_POWER_W = 1700

SENSOR_DEFINITIONS = [
    {"key": "battery_soc", "name": "Battery SOC", "unit": "%", "device_class": "battery", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "medium", "enabled_by_default": True},
    {"key": "battery_power", "name": "Battery Power", "unit": "W", "device_class": "power", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "high", "enabled_by_default": True},
    {"key": "battery_voltage", "name": "Battery Voltage", "unit": "V", "device_class": "voltage", "state_class": "measurement", "scale": 0.001, "precision": 1, "scan_interval": "medium", "enabled_by_default": True},
    {"key": "power_setpoint", "name": "Power Setpoint", "unit": "W", "device_class": "power", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "medium", "enabled_by_default": False},
    {"key": "pv_power", "name": "PV Power", "unit": "W", "device_class": "power", "state_class": "measurement", "scale": 1, "precision": 0, "scan_interval": "high", "enabled_by_default": False},
    {"key": "total_charging_energy", "name": "Total Charging Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "scale": 0.001, "precision": 3, "scan_interval": "low", "enabled_by_default": True},
    {"key": "total_discharging_energy", "name": "Total Discharging Energy", "unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "scale": 0.001, "precision": 3, "scan_interval": "low", "enabled_by_default": True},
    {"key": "wifi_signal_strength", "name": "WiFi Signal Strength", "unit": "dBm", "device_class": "signal_strength", "state_class": "measurement", "scale": 1, "precision": 0, "icon": "mdi:wifi", "category": "diagnostic", "scan_interval": "low", "enabled_by_default": True},
    {"key": "software_version", "name": "Software Version", "data_type": "char", "icon": "mdi:ticket-confirmation-outline", "category": "diagnostic", "scan_interval": "low", "enabled_by_default": True},
]

_POWER_KEYS = frozenset({
    "battery_soc",
    "battery_power",
    "battery_voltage",
    "power_setpoint",
    "pv_power",
})
_ENERGY_KEYS = frozenset({"total_charging_energy", "total_discharging_energy"})
_DEVICE_INFO_KEYS = frozenset({"wifi_signal_strength", "software_version"})


class SessyLocalDriver(BatteryDriver):
    """Poll and control one Sessy dongle using its documented local API."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 80,
        username: str = "",
        password: str = "",
        max_charge_power_w: int = _MAX_CHARGE_POWER_W,
        max_discharge_power_w: int = _MAX_DISCHARGE_POWER_W,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._base_url = f"http://{host}" + (f":{port}" if port != 80 else "")
        self._headers = (
            {"Authorization": aiohttp.BasicAuth(username, password).encode()}
            if username or password
            else None
        )
        self._session = session
        self._owns_session = False
        self._connected = False
        self._shutting_down = False
        max_charge_power_w = max(0, min(int(max_charge_power_w), _MAX_CHARGE_POWER_W))
        max_discharge_power_w = max(0, min(int(max_discharge_power_w), _MAX_DISCHARGE_POWER_W))
        self._capabilities = DriverCapabilities(False, False, False, max_charge_power_w,
            max_discharge_power_w, False, False, False, has_daily_energy_counters=False,
            has_nominal_capacity=False,
            cycles_from_discharge_only=True,
            # Sessy can take up to a minute to leave standby after receiving its
            # first non-zero setpoint. Keep the physical direction-change timing
            # independent from that startup/safety transition, but do not let the
            # controller judge the still-zero output as a failed battery.
            actuator_latency_s=1.5,
            readback_latency_s=60.0,
            engage_grace_s=60.0)
        self._read_groups = [
            ReadGroup("high", tuple(key for key in _POWER_KEYS)),
            ReadGroup("low", tuple(key for key in _ENERGY_KEYS)),
            ReadGroup("low", tuple(key for key in _DEVICE_INFO_KEYS)),
        ]

    @property
    def capabilities(self) -> DriverCapabilities: return self._capabilities
    @property
    def model_label(self) -> Optional[str]: return "Sessy"
    @property
    def connected(self) -> bool: return self._connected
    @property
    def read_groups(self) -> list[ReadGroup]: return self._read_groups
    @property
    def sensor_definitions(self) -> list[dict]: return SENSOR_DEFINITIONS
    @property
    def number_definitions(self) -> list[dict]: return []
    @property
    def select_definitions(self) -> list[dict]: return []
    @property
    def switch_definitions(self) -> list[dict]: return []
    @property
    def binary_sensor_definitions(self) -> list[dict]: return []
    @property
    def button_definitions(self) -> list[dict]: return []
    @property
    def all_definitions(self) -> list[dict]: return SENSOR_DEFINITIONS

    async def connect(self) -> bool:
        self._ensure_session()
        self._connected = await self._get_status() is not None
        return self._connected

    async def close(self) -> None:
        self._connected = False
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def set_shutting_down(self, value: bool) -> None: self._shutting_down = value

    async def read_telemetry(self, keys: Optional[list[str]] = None) -> TelemetrySnapshot:
        requested = set(keys) if keys is not None else set(
            _POWER_KEYS | _ENERGY_KEYS | _DEVICE_INFO_KEYS
        )
        snapshot = {}

        if requested & _POWER_KEYS:
            status = await self._get_status()
            if status:
                sessy = status.get("sessy", {})
                phases = [
                    status.get(f"renewable_energy_phase{i}", {})
                    for i in range(1, 4)
                ]
                snapshot.update({
                    "battery_soc": (
                        sessy["state_of_charge"] * 100
                        if "state_of_charge" in sessy
                        else None
                    ),
                    "battery_power": -sessy["power"] if "power" in sessy else None,
                    "battery_voltage": sessy.get("pack_voltage"),
                    "power_setpoint": sessy.get("power_setpoint"),
                    "pv_power": sum(p.get("power", 0) for p in phases),
                })

        if requested & _ENERGY_KEYS:
            energy = await self._get_json("/api/v1/energy/status")
        else:
            energy = None
        if energy:
            meters = energy.get("sessy_energy", {})
            snapshot["total_charging_energy"] = meters.get("import_wh")
            snapshot["total_discharging_energy"] = meters.get("export_wh")

        if "wifi_signal_strength" in requested:
            network = await self._get_json("/api/v1/network/status")
            wifi = network.get("wifi_sta", {}) if network else {}
            snapshot["wifi_signal_strength"] = wifi.get("rssi")

        if "software_version" in requested:
            ota = await self._get_json("/api/v1/ota/status")
            ota_self = ota.get("self", {}) if ota else {}
            installed = ota_self.get("installed_firmware", {})
            snapshot["software_version"] = installed.get("version")

        snapshot = {key: value for key, value in snapshot.items() if value is not None}
        return snapshot if keys is None else {key: value for key, value in snapshot.items() if key in keys}

    async def apply_setpoint(self, net_power_w: int, *, mode_hint: Optional[str] = None,
                             read_back: bool = True) -> SetpointResult:
        applied = max(-self._capabilities.max_discharge_power_w,
                      min(self._capabilities.max_charge_power_w, int(net_power_w)))
        # Sessy positive = generation (discharge); Omnibattery positive = charge.
        if not await self._post_json("/api/v1/power/active_strategy", {"strategy": _API_STRATEGY}):
            return SetpointResult(False, applied, False, failure_reason="strategy_write_failed")
        if not await self._post_json("/api/v1/power/setpoint", {"setpoint": -applied}):
            return SetpointResult(False, applied, False, failure_reason="setpoint_write_failed")
        if not read_back:
            return SetpointResult(True, applied, False, applied={"power_setpoint": -applied})
        status = await self._get_status()
        sessy = status.get("sessy", {}) if status else {}
        confirmed = sessy.get("power_setpoint") == -applied
        measured = -sessy["power"] if "power" in sessy else None
        return SetpointResult(True, applied, confirmed, battery_power_w=measured,
            applied={"power_setpoint": -applied, **({"battery_power": measured} if measured is not None else {})})

    async def write_control(self, key: str, value: int) -> bool: return False
    def net_power_from_data(self, data: dict) -> Optional[int]:
        value = data.get("power_setpoint")
        return -int(value) if value is not None else None
    @property
    def control_dependency_keys(self) -> frozenset: return frozenset({"power_setpoint"})
    async def apply_config(self, **kwargs) -> bool: return True
    async def set_charge_cutoff(self, soc_pct: float) -> bool: return False
    async def standby(self) -> bool: return (await self.apply_setpoint(0, read_back=False)).ok
    async def set_rs485_control(self, enable: bool) -> bool: return False

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers)
            self._owns_session = True
        return self._session

    async def _get_json(self, path: str) -> Optional[dict]:
        try:
            async with self._ensure_session().get(self._base_url + path, timeout=_HTTP_TIMEOUT) as response:
                return await response.json(content_type=None) if response.status == 200 else None
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as exc:
            if not self._shutting_down: _LOGGER.warning("Sessy GET %s failed: %s", path, exc)
            return None

    async def _get_status(self) -> Optional[dict]: return await self._get_json("/api/v1/power/status")

    async def _post_json(self, path: str, body: dict) -> bool:
        try:
            async with self._ensure_session().post(self._base_url + path, json=body, timeout=_HTTP_TIMEOUT) as response:
                return response.status == 200
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if not self._shutting_down: _LOGGER.warning("Sessy POST %s failed: %s", path, exc)
            return False

    @classmethod
    async def probe(
        cls, host: str, port: int = 80, username: str = "", password: str = ""
    ) -> bool:
        driver = cls(host, port=port, username=username, password=password)
        try: return await driver.connect()
        finally: await driver.close()
