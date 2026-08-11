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
| `HB-4020-X`, `HB-4020-XM` | HiBattery 4020 X | 4.02 kWh per pack, up to 16.08 kWh | Current integration ceiling: 2500/2500 W charge/discharge |
| `HB-4020-AC`, `HB-4020-ACM` | HiBattery 4020 AC | 4.02 kWh per pack, up to 16.08 kWh | Current integration ceiling: 2500/2500 W charge/discharge |

¹ The retained MQTT `min`/`max` envelope is authoritative and may be lower or
asymmetric for a particular hardware variant, country setting or firmware.

The 4020 X manual specifies higher battery-side limits for larger expansion
stacks, while the current 4020 AC manual (REV1.2) documents expansion-dependent
limits as well. Omnibattery currently uses a symmetric software ceiling of
`2500/2500 W` for both 4020 variants. Higher power operation for larger stacks
is intentionally out of scope; open a feature request before extending it.
The device-published MQTT envelope remains authoritative and can reduce the
effective limit. Capacity can still reflect expansion packs.

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
base 4020 X, for example, uses a `4.02 kWh` capacity and a `2500/2500 W`
software ceiling instead of inheriting the MS-A2's `2.24 kWh` and `1000/1000 W`
defaults. Any lower limit advertised by the individual device is preserved.

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
