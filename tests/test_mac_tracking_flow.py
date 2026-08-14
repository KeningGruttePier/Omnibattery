"""Flow-level tests for the DHCP step that applies a MAC-tracked address change.

The decision guards are unit-tested in ``test_mac_tracking``; what is checked
here is the wiring: that a refused verdict leaves the config entry strictly
alone, that an accepted one rewrites the host *and* goes through the existing
registry migration, and that the migration keeps the entity ids — which is what
preserves history and long-term statistics.

Written against small stubs rather than the ``hass`` fixture: ``pytest.ini``
disables the Home Assistant plugin and CI runs a bare ``pytest``, so a
fixture-based test would be skipped everywhere.
"""

from __future__ import annotations

import types

import pytest

from custom_components.omnibattery import config_flow as cf
from custom_components.omnibattery.infra.mac_tracking import CONF_MAC, CONF_TRACK_MAC

MAC_A = "dc:04:5a:14:6b:33"
MAC_B = "dc:04:5a:7d:de:c6"


# --- stubs ------------------------------------------------------------------


class FakeEntry:
    def __init__(self, batteries, entry_id="entry1", title="Omnibattery"):
        self.entry_id = entry_id
        self.title = title
        self.data = {"batteries": batteries, "consumption_sensor": "sensor.grid"}


class FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self.updated = []
        self.reloaded = []

    def async_entries(self, domain):
        return list(self._entries)

    def async_update_entry(self, entry, data=None, **kwargs):
        entry.data = data
        self.updated.append((entry.entry_id, data))
        return True

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)
        return True


class FakeHass:
    def __init__(self, entries, coordinators=None):
        self.config_entries = FakeConfigEntries(entries)
        self.data = {cf.DOMAIN: {"entry1": {"coordinators": coordinators or []}}}


def battery(host="192.168.1.181", mac=MAC_A, track=True, name="Marstek Venus 2"):
    return {
        "name": name,
        "host": host,
        "port": 502,
        "slave_id": 1,
        "brand": "marstek",
        "serial_port": "",
        CONF_TRACK_MAC: track,
        CONF_MAC: mac,
    }


def make_flow(hass, migrations):
    """A config flow instance wired to ``hass``, recording registry migrations."""
    flow = cf.MarstekVenusConfigFlow()
    flow.hass = hass
    flow._migrate_battery_registry_ids = lambda *args: migrations.append(args)
    return flow


def lease(mac, ip):
    return types.SimpleNamespace(macaddress=mac, ip=ip)


# --- the opt-in is off: nothing at all happens ------------------------------


async def test_disabled_tracking_leaves_the_entry_untouched():
    hass = FakeHass([FakeEntry([battery(track=False)])])
    migrations: list = []
    flow = make_flow(hass, migrations)

    reason = await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180")

    assert reason == "no_tracked_battery"
    assert hass.config_entries.updated == []
    assert hass.config_entries.reloaded == []
    assert migrations == []


async def test_an_unknown_mac_leaves_the_entry_untouched():
    hass = FakeHass([FakeEntry([battery(mac=MAC_A)])])
    migrations: list = []
    flow = make_flow(hass, migrations)

    assert await flow._async_apply_dhcp_lease("aa:bb:cc:dd:ee:ff", "192.168.1.180") == "no_tracked_battery"
    assert hass.config_entries.updated == []


# --- the nominal move -------------------------------------------------------


async def test_a_tracked_battery_is_moved_and_the_entry_reloaded():
    entry = FakeEntry([battery(host="192.168.1.181")])
    hass = FakeHass([entry])
    migrations: list = []
    flow = make_flow(hass, migrations)

    reason = await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180")

    assert reason == "ip_updated"
    assert entry.data["batteries"][0]["host"] == "192.168.1.180"
    assert hass.config_entries.reloaded == [entry.entry_id]
    # Other keys of the battery survive untouched.
    assert entry.data["batteries"][0][CONF_MAC] == MAC_A
    assert entry.data["consumption_sensor"] == "sensor.grid"


async def test_the_registry_migration_is_called_with_the_old_and_new_endpoint():
    """This call is what keeps entity ids, history and statistics."""
    entry = FakeEntry([battery(host="192.168.1.181")])
    hass = FakeHass([entry])
    migrations: list = []
    flow = make_flow(hass, migrations)

    await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180")

    assert len(migrations) == 1
    called_entry, old_host, old_port, new_host, new_port, old_slave, new_slave = migrations[0]
    assert called_entry is entry
    assert (old_host, old_port) == ("192.168.1.181", 502)
    assert (new_host, new_port) == ("192.168.1.180", 502)
    assert old_slave == new_slave == 1


async def test_only_the_matching_battery_moves():
    entry = FakeEntry([battery(host="192.168.1.64", mac=MAC_B), battery(host="192.168.1.181", mac=MAC_A)])
    hass = FakeHass([entry])
    flow = make_flow(hass, [])

    await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180")

    assert entry.data["batteries"][0]["host"] == "192.168.1.64"
    assert entry.data["batteries"][1]["host"] == "192.168.1.180"


# --- guards seen from the flow ---------------------------------------------


async def test_a_battery_still_answering_is_left_where_it_is():
    """A device holding two addresses must not be pulled off a working one."""
    entry = FakeEntry([battery(host="192.168.1.181")])
    live = types.SimpleNamespace(is_available=True)
    hass = FakeHass([entry], coordinators=[live])
    flow = make_flow(hass, [])

    assert await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180") == "no_tracked_battery"
    assert entry.data["batteries"][0]["host"] == "192.168.1.181"
    assert hass.config_entries.updated == []


async def test_a_quiet_battery_is_moved():
    entry = FakeEntry([battery(host="192.168.1.181")])
    quiet = types.SimpleNamespace(is_available=False)
    hass = FakeHass([entry], coordinators=[quiet])
    flow = make_flow(hass, [])

    assert await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.180") == "ip_updated"


async def test_a_renewed_lease_for_the_current_address_does_not_reload():
    entry = FakeEntry([battery(host="192.168.1.181")])
    hass = FakeHass([entry])
    flow = make_flow(hass, [])

    assert await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.181") == "no_tracked_battery"
    assert hass.config_entries.reloaded == []


async def test_a_shared_gateway_mac_moves_nothing():
    entry = FakeEntry(
        [
            battery(host="192.168.1.50", mac=MAC_A) | {"slave_id": 1},
            battery(host="192.168.1.50", mac=MAC_A) | {"slave_id": 2},
        ]
    )
    hass = FakeHass([entry])
    flow = make_flow(hass, [])

    assert await flow._async_apply_dhcp_lease(MAC_A, "192.168.1.51") == "no_tracked_battery"
    assert hass.config_entries.updated == []


# --- the migration helper actually preserves entity ids ---------------------


class FakeRegistryEntry:
    def __init__(self, entity_id, unique_id, config_entry_id):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class FakeEntityRegistry:
    def __init__(self, entries):
        self.entities = {e.entity_id: e for e in entries}
        self.calls: list = []

    def async_update_entity(self, entity_id, **kwargs):
        self.calls.append((entity_id, kwargs))
        if "new_unique_id" in kwargs:
            self.entities[entity_id].unique_id = kwargs["new_unique_id"]


class FakeDeviceRegistry:
    def __init__(self, device):
        self.device = device
        self.updates: list = []

    def async_get_device(self, identifiers=None, **kwargs):
        return self.device if identifiers == self.device.identifiers else None

    def async_update_device(self, device_id, new_identifiers=None, **kwargs):
        self.updates.append((device_id, new_identifiers))


def test_migration_rewrites_unique_ids_but_never_entity_ids(monkeypatch):
    """Long-term statistics follow the entity_id, so it must survive a move."""
    entry = FakeEntry([battery()])
    entities = [
        FakeRegistryEntry("sensor.marstek_venus_2_battery_soc", "192.168.1.181_502_battery_soc", entry.entry_id),
        FakeRegistryEntry("sensor.marstek_venus_2_battery_power", "192.168.1.181_502_battery_power", entry.entry_id),
        FakeRegistryEntry("sensor.other_integration", "somethingelse_soc", "other_entry"),
    ]
    ent_reg = FakeEntityRegistry(entities)
    device = types.SimpleNamespace(id="dev1", identifiers={(cf.DOMAIN, "192.168.1.181_502")})
    dev_reg = FakeDeviceRegistry(device)

    monkeypatch.setattr(cf.er, "async_get", lambda hass: ent_reg)
    monkeypatch.setattr(cf.dr, "async_get", lambda hass: dev_reg)

    flow = cf.MarstekVenusConfigFlow()
    flow.hass = FakeHass([entry])
    flow._migrate_battery_registry_ids(entry, "192.168.1.181", 502, "192.168.1.180", 502, 1, 1)

    # unique_ids re-prefixed onto the new endpoint...
    assert entities[0].unique_id == "192.168.1.180_502_battery_soc"
    assert entities[1].unique_id == "192.168.1.180_502_battery_power"
    # ...an unrelated integration untouched...
    assert entities[2].unique_id == "somethingelse_soc"
    # ...and no call ever asked to change an entity_id.
    assert all("new_entity_id" not in kwargs for _eid, kwargs in ent_reg.calls)
    assert {e.entity_id for e in entities} == {
        "sensor.marstek_venus_2_battery_soc",
        "sensor.marstek_venus_2_battery_power",
        "sensor.other_integration",
    }
    # The device identifier follows the same rename.
    assert dev_reg.updates == [("dev1", {(cf.DOMAIN, "192.168.1.180_502")})]
