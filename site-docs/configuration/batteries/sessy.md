# Sessy Home Battery

Omnibattery connects to a Sessy through the local HTTP API exposed by its
dongle. The Sessy support is still looking for testers, so report any model or
firmware-specific behaviour when asking for help.

## Connection

The dongle must be reachable from Home Assistant. Enter the host or IP, HTTP
port and the credentials printed on the dongle.

| Field | Description | Default |
|---|---|---|
| **Name** | Name used for the battery device | — |
| **Host** | IP address or hostname of the Sessy dongle | — |
| **HTTP port** | Local API port | `80` |
| **Username** | Dongle/API username | — |
| **Password** | Dongle/API password | — |

The wizard tests the local API before continuing. Keep the API local; no cloud
connection is required by Omnibattery.

## Limits and capacity

Sessy uses asymmetric hardware limits of `2200 W` for charging and `1700 W` for
discharging. These values are seeded by the integration rather than entered as
free-form hardware limits during setup.

The wizard requires the nominal battery capacity in kWh (`0.01–100 kWh`),
because the Sessy API does not provide a nominal capacity counter. It also
configures the common SOC limits, charge hysteresis and backup offgrid
threshold. The default minimum SOC is `5%` and the maximum is `100%`.

Sessy does not expose Marstek's cell-voltage taper. See [Battery
configuration](index.md) for the common runtime controls and system power
limits.
