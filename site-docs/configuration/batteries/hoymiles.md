# Hoymiles MS-A2

The Hoymiles MS-A2 communicates with Omnibattery through the MQTT integration
already configured in Home Assistant. Omnibattery does not need the broker's
host, port or credentials; Home Assistant handles the MQTT connection.

## Prerequisites

Before adding the battery:

- commission the MS-A2 in **S-Miles Home**;
- use firmware that exposes **MQTT Service**;
- configure a local MQTT broker through Home Assistant;
- make the broker reachable from the MS-A2;
- note the complete MQTT device ID, normally similar to `MSA-280024341346`.

The [complete Hoymiles installation guide](../hoymiles-ms-a2.md) covers the
electrical installation, S-Miles Home, MQTT and verification steps.

## Connection

Choose **Hoymiles MS-A2** as the brand and enter only a descriptive name and the
full MQTT device ID. The connection test listens for live telemetry through
Home Assistant.

| Field | Description |
|---|---|
| **Name** | Name used for the battery device |
| **MQTT device ID** | Full MS-A2 ID, including the `MSA-` prefix |

No IP address, HTTP port, MQTT sensor or manual MQTT automation is required.

## Capacity and limits

An individual MS-A2 has a nominal capacity of `2.24 kWh`; a supported paired
system normally uses `4.48 kWh`. Enter the applicable nominal capacity in the
limits step.

The power envelope is detected from MQTT and capped at `2000 W`; a standalone
unit is normally limited to `1000 W` in both directions. The common limits also
include maximum SOC, minimum SOC and charge hysteresis. The default minimum SOC
is `10%`.

The MQTT protocol does not expose writable SOC cutoffs or individual cell
voltages. Omnibattery therefore enforces SOC limits in software, and Marstek's
cell-balance and voltage-taper features are unavailable for the MS-A2.

For runtime controls and system limits, see [Battery configuration](index.md).
