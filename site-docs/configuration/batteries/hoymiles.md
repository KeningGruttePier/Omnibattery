# Hoymiles MQTT batteries

Supported Hoymiles micro-storage batteries communicate with Omnibattery through
the MQTT integration already configured in Home Assistant. Omnibattery does not
need the broker host, port or credentials; Home Assistant manages the connection.

## Supported models

Omnibattery reads `device.model` and the signed `min`/`max` power envelope from
the retained MQTT discovery payload. The detected profile supplies the nominal
capacity and the model-specific safety ceiling; the advertised envelope remains
the final device limit.

| MQTT model | Product | Capacity | Profile safety ceiling¹ |
|---|---|---:|---:|
| `MS-A2`, `MS-A2-FX`, `MS-A2-ZZ` | MS-A2 | 2.24 kWh per unit, up to 4.48 kWh | 1000 W per unit, up to 2000 W |
| `HB-1920-AC-SV` | HiBattery 1920 AC | 1.92 kWh per unit, up to 11.52 kWh | 1000 W per unit, up to 6000 W |
| `HB-4020-X`, `HB-4020-XM` | HiBattery 4020 X | 4.02 kWh per pack, up to 16.08 kWh | Base: 2000/2000 W; expanded: up to 6500/2500 W charge/discharge |
| `HB-4020-AC`, `HB-4020-ACM` | HiBattery 4020 AC | 4.02 kWh per pack, up to 16.08 kWh | Base: 2000/2000 W; expanded: up to 2500/2500 W charge/discharge |

¹ The retained MQTT `min`/`max` envelope is authoritative and may be lower or
asymmetric for a particular hardware variant, country setting or firmware.

The 4020 X manual specifies the following battery-side limits for the main unit
plus zero to three HB-4020-S expansion packs: `2000/2000`, `4000/2500`,
`6000/2500` and `6500/2500 W` charge/discharge. The current 4020 AC manual
(REV1.2) specifies `2000/2000 W` without an expansion and `2500/2500 W` with
one or more expansions. Separately, the non-M on-grid variants are rated for
800 W output while XM/ACM are rated for 2500 W; this is not the same value as
battery-side charge/discharge power. Omnibattery allows the full family safety
ceiling but always reduces it to the signed range published by that particular
system over MQTT. Verify the configured capacity when expansion packs are
installed.

## Prerequisites

Before adding the battery:

- commission it in **S-Miles Home**;
- use firmware that exposes **MQTT Service**;
- configure a local MQTT broker through Home Assistant;
- make the broker reachable from the battery;
- note the complete MQTT device ID, commonly similar to `MSA-280024341346`.

The [MS-A2 installation guide](../hoymiles-ms-a2.md) covers broker setup,
S-Miles Home and verification. The MQTT steps also apply to the supported
HiBattery models; follow the product's own manual for electrical installation.

## Connection and limits

Choose **Hoymiles MQTT** as the brand and enter a descriptive name and the full
MQTT device ID. Leave **Battery model** on **Auto-detect** normally. If firmware
publishes an incorrect or generic model, select the installed model explicitly;
the live MQTT power envelope still remains the final limit. The connection test
waits for live telemetry and the retained power-control discovery payload. No IP
address, HTTP port, manual MQTT sensor or automation is required.

The next step shows the detected capacity and charge/discharge limits. These
remain editable software ceilings and can be reduced for the installation. A
base 4020 X, for example, uses a `4.02 kWh` capacity and `2000/2000 W`
charge/discharge profile instead of inheriting the MS-A2's `2.24 kWh` and
`1000/1000 W`. Expansion configurations can advertise the higher limits listed
above, while a lower limit advertised by an individual device is preserved.

The MQTT protocol does not expose writable SOC cutoffs or individual cell
voltages. Omnibattery therefore enforces SOC limits in software, and the
Marstek-specific cell-balance and voltage-taper features are unavailable.

Existing entries created by the former MS-A2-only flow are corrected when the
Hoymiles connection is reconfigured: if discovery identifies another model,
only the old `1000 W` / `2.24 kWh` defaults are replaced by that profile. Select
the model manually during reconfiguration if the old firmware cannot identify
it correctly.

For runtime controls and system limits, see [Battery configuration](index.md).

## Manufacturer references

- [Hoymiles MQTT protocol guide](https://www.hoymiles.com/uploadfile/1/202511/9350aa1077.txt)
- [HiBattery 1920 AC](https://www.hoymiles.com/products/hibattery-1920-ac.html)
- [HiBattery 4020 X datasheet](https://www.hoymiles.com/uploadfile/1/202606/95d670b3a3.pdf)
- [HiBattery 4020 X user manual](https://www.hoymiles.com/downloads/user-manual-hb-4020-x-global-en-de-fr-nl.html)
- [HiBattery 4020 AC](https://www.hoymiles.com/products/hibattery-4020-ac.html)
- [HiBattery 4020 AC user manual](https://www.hoymiles.com/downloads/user-manual-hb-4020-ac-global-en-de-fr-nl.html)
