# Install and configure a Hoymiles MS-A2

This guide covers the complete path from a commissioned MS-A2 to control through
Omnibattery. The battery communicates locally through the MQTT broker already
configured in Home Assistant; Omnibattery does not need separate broker
credentials.

## Before you start

You need:

- a Hoymiles MS-A2 commissioned in **S-Miles Home**;
- MS-A2 firmware that shows **MQTT Service** in the app;
- Home Assistant with the **MQTT** integration and a working broker;
- OmniBattery installed and a grid power sensor available;
- the MS-A2 MQTT device ID, normally similar to `MSA-280024341346`.

!!! warning "Electrical installation"
    Follow the current [official MS-A2 installation guide](https://www.hoymiles.com/statics/5/hoymiles/picture/User-Manual_MS_A2_Global_EN_REV1.4.pdf), the product labels and local electrical regulations. Turn off the MS-A2 and isolate the microinverter/PV system before changing AC connections. This page does not replace the manufacturer's safety instructions.

## 1. Install and commission the battery

1. Check that the MS-A2, plug-and-play cable and connectors are undamaged.
2. Install the unit in an allowed upright position with the clearances,
   temperature limits and weather protection specified by Hoymiles.
3. With the equipment isolated, connect the microinverter system and the AC
   on-grid cable exactly as shown in the official installation guide.
4. Connect the on-grid cable to the approved Schuko outlet and turn on the
   MS-A2.
5. Add the battery in **S-Miles Home**, connect it to 2.4 GHz Wi-Fi and confirm
   that SOC and power are updating in the app.
6. Install any firmware update offered by Hoymiles. Continue only when the app
   exposes **MQTT Service** for the battery.

The MS-A2 is AC-coupled and has a nominal capacity of `2.24 kWh`. A supported
two-unit system normally uses `4.48 kWh` as its nominal capacity in
Omnibattery.

## 2. Prepare MQTT in Home Assistant

If MQTT is already working for other devices, reuse that broker.

1. In Home Assistant, open **Settings → Devices & services**.
2. Confirm that the **MQTT** integration is configured and connected.
3. Create a dedicated broker user for the MS-A2 if your broker supports users.
4. Note the broker's LAN address, port and credentials. The default unencrypted
   MQTT port is usually `1883`.

!!! danger "Do not expose MQTT to the Internet"
    Keep the broker on the local network or behind a properly secured VPN. Do
    not forward port `1883` from the router to the Internet.

## 3. Point the MS-A2 at the broker

In **S-Miles Home**:

1. Open the MS-A2 settings and select **MQTT Service**.
2. Enable the service.
3. Enter the MQTT broker's LAN IP or hostname, port, username and password.
4. Save the settings and wait for the MS-A2 to reconnect.
5. Record the complete MQTT device ID shown by the app or broker. Keep the
   `MSA-` prefix.

The MS-A2 should publish a message approximately every second on:

```text
homeassistant/sensor/<device_id>/quick/state
```

For example:

```text
homeassistant/sensor/MSA-280024341346/quick/state
```

You do not need to create MQTT sensors or automations manually. Omnibattery
subscribes directly through Home Assistant.

## 4. Add the battery to Omnibattery

1. Open **Settings → Devices & services → Add integration** and select
   **Omnibattery**. To modify an existing installation, open Omnibattery and
   choose **Configure**.
2. Select the grid import/export sensor and the number of batteries.
3. Choose **Hoymiles MS-A2** as the battery brand.
4. Enter a descriptive name and the full MQTT device ID.
5. Wait for the connection test. It listens for live SOC and battery power; it
   can take a few seconds.
6. Configure the limits:

    | Setting | Recommended starting value |
    |---|---:|
    | Nominal capacity, one MS-A2 | `2.24 kWh` |
    | Nominal capacity, paired system | `4.48 kWh` |
    | Maximum charge/discharge power | `1000 W` per unit; keep the safely detected limit |
    | Maximum SOC | `100 %` |
    | Minimum SOC | `10 %` |
    | Charge hysteresis | `2 %` |

7. Complete the remaining Omnibattery wizard and verify that the battery device
   exposes SOC, power, voltage, temperature and daily energy entities.

## How control works

Omnibattery converts its standard signed power convention to the Hoymiles
protocol automatically:

- positive Omnibattery power charges the battery;
- negative Omnibattery power discharges it;
- zero holds the battery idle.

When control is active, the driver selects `mqtt_ctrl` and renews the exact
command about every 30 seconds. Identical payloads renew the device timeout, so
the requested setpoint is not altered. A failed renewal is retried after
5 seconds. This is required because the MS-A2 returns to its internal logic
about 62 seconds after external MQTT commands stop. When Omnibattery unloads,
it sends `0 W` and restores `general`.

Firmware `01.06.03` advertises a `-1000…+2000 W` MQTT envelope for one MS-A2
even though the standalone hardware is limited to 1000 W in both directions.
Omnibattery therefore derives a symmetric limit from the charge-side magnitude
and never raises the ceiling selected during setup. A paired system whose
retained envelope is `-2000…+2000 W` keeps its 2 kW range.

SOC limits are enforced by Omnibattery software because the MQTT protocol does
not expose writable MS-A2 SOC cutoffs. Cell-voltage balance and voltage-taper
features are unavailable because the protocol does not report individual cell
voltages.

## Verification checklist

After setup, confirm all of the following:

- the Omnibattery battery device is available;
- SOC changes match S-Miles Home;
- charging appears as positive battery power in Omnibattery;
- discharging appears as negative battery power;
- a small manual charge, discharge and idle command is followed by the battery;
- MQTT telemetry continues updating locally through the broker;
- the configured power and SOC limits match the installation.

Start with low power while verifying the direction. Stop the test immediately
if the observed direction is not the requested one.

## Troubleshooting

| Symptom | Checks |
|---|---|
| **Cannot connect** in the wizard | Confirm the Home Assistant MQTT integration is connected, the MS-A2 MQTT service is enabled, and the full `MSA-…` ID is correct. |
| The app works but Omnibattery receives no data | Check the broker IP, port and credentials in S-Miles Home. The broker must be reachable from the battery's Wi-Fi network. |
| The battery returns to autonomous control | Check for MQTT disconnects or broker restarts. Omnibattery must be able to renew the command before the one-minute timeout. |
| Power is limited to 1 kW on a paired system | Reconfigure the battery after both units are paired so Omnibattery can read the retained power envelope. Supported MS-A2 systems are capped at 2 kW. |
| SOC works but detailed entities update slowly | `quick/state` updates about every second; voltage, temperature and daily energy topics are normally published about every five minutes. |
| Control is rejected | Update the MS-A2 firmware, confirm that the selected ID belongs to the master/standalone unit and reconnect its MQTT service. |

## Official references

- [Hoymiles MS-A2 product page](https://www.hoymiles.com/products/micro-storage.html)
- [MS-A2 installation/user guide](https://www.hoymiles.com/statics/5/hoymiles/picture/User-Manual_MS_A2_Global_EN_REV1.4.pdf)
- [Hoymiles MQTT protocol guide](https://www.hoymiles.com/uploadfile/1/202511/9350aa1077.txt)
