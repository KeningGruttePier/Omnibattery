# Three-phase current protection

Three-phase current protection is an optional safety envelope for installations where the batteries share a three-phase connection. It is **disabled by default** and can be configured in the initial setup or from **Settings → Integrations → Omnibattery → Configure → Sensors**.

## Configuration

Enable the feature and select one real-time signed RMS current sensor and one fuse-size/current limit in amperes for each phase you want to protect. Leave both fields empty for unused phases, so a one- or two-phase installation does not need placeholder values for the remaining phases. The sensors must be Home Assistant `sensor` entities with an `A` or `mA` unit. They use the same convention as the global grid sensor:

- positive = grid import
- negative = grid export

The global **Inverted meter sign** setting is applied to the configured phase meters and Grid 0. Set one positive symmetric fuse-size/current limit in amperes for each configured phase, preferably below the fuse nameplate rating to leave operating margin. The physical phase assignment (`L1`, `L2` or `L3`) is required for every battery; Omnibattery cannot discover which AC phase a battery is wired to. A battery assigned to a phase without a sensor and limit operates normally, without a phase protection cap.

The global consumption sensor remains the controller's Grid 0 signal. Phase sensors are safety envelopes only: they do not replace Grid 0 or change the PD target.

## How the envelope works

For each phase, Omnibattery reconstructs the non-battery current and calculates both directional budgets:

```text
base_current = phase_current - battery_current_on_phase
charge_budget_current = max(0, fuse_size - base_current)
discharge_budget_current = max(0, fuse_size + base_current)
```

The current sensor must be signed: positive means import and negative means export. Battery telemetry and commands use the controller convention (`+` charge, `−` discharge) and remain in active watts. Internally, battery watts are converted to current and the available current budget is converted back to a conservative watt cap using 230 V nominal voltage and a 0.90 power factor. The normal load-sharing selection and proportional allocation run first. The result is then rounded down in 5 W increments and capped independently on each phase. Only power rejected by that cap is moved to batteries on healthy phases with remaining capacity, following the normal SOC/energy priority order.

The envelope is applied to normal PD and direct-tracking control, predictive grid charging, automatic time-slot PD, active-balance rebalances and the final common automatic command guard. The assigned total is fed back into the controller so a phase cap does not create integral windup.

If a configured phase sensor is missing, unavailable, non-numeric, in the wrong unit or older than 65 seconds, batteries assigned to that phase receive 0 W. The sensor must be signed; an unsigned current sensor cannot represent export correctly and should not be used for this feature. A phase left unconfigured has no phase protection, so batteries assigned to it continue under the normal controller and per-battery limits. Other healthy phases continue operating. Sensor recovery is picked up on the next report.

## Important limitations

Manual register writes and manual time-slot commands intentionally remain direct and can bypass this software envelope. Home Assistant shows a Repairs warning while the feature is enabled; keep those commands within the electrical limit.

This is a conservative current guard, not a replacement for breakers, inverter protection or an electrician's design. Use a true-RMS sensor with a reliable import/export sign and leave margin below the fuse nameplate rating for measurement latency, actuator latency, external loads, voltage, power factor, harmonics and transient peaks. The internal 230 V/0.90 conversion is an estimate for translating the battery's active-watt commands into an RMS-current budget; the current sensor remains the source of the phase safety measurement. An external load can exceed a phase limit by itself, while Omnibattery can only avoid making that excess worse. The global controller does not issue simultaneous charge on one phase and discharge on another. The sensors must be installed and mapped to the actual conductors; an incorrect L1/L2/L3 assignment cannot be detected automatically.

The beta configuration uses current-sensor and fuse-size fields. There is intentionally no migration from the previous phase-power fields, so re-enter the phase protection settings after upgrading.
