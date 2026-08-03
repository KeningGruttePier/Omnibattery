# Three-phase power protection

Three-phase protection is an optional safety envelope for installations where the
batteries share a three-phase connection. It is **disabled by default** and can be
configured in the initial setup or from **Settings → Integrations → Omnibattery →
Configure → Sensors**.

## Configuration

Enable the feature and select one real-time power sensor for **L1**, **L2** and
**L3**. The sensors must be Home Assistant `sensor` entities with a `W` or `kW`
unit. They use the same convention as the global grid sensor:

- positive = grid import
- negative = grid export

The global **Inverted meter sign** setting is applied to all four grid meters. Set
one positive symmetric maximum power in watts for each phase. The physical phase
assignment (`L1`, `L2` or `L3`) is required for every battery; Omnibattery cannot
discover which AC phase a battery is wired to.

The global consumption sensor remains the controller's Grid 0 signal. Phase
sensors are safety envelopes only: they do not replace Grid 0 or change the PD
target.

## How the envelope works

For each phase, Omnibattery reconstructs the non-battery load and calculates both
directional budgets:

```text
base_load = grid_reading - battery_power_on_phase
charge_budget = max(0, limit - grid_reading + battery_power_on_phase)
discharge_budget = max(0, limit + grid_reading - battery_power_on_phase)
```

Battery power uses the controller convention (`+` charge, `−` discharge). The
normal load-sharing selection and proportional allocation run first. The result
is then rounded down in 5 W increments and capped independently on each phase.
Only power rejected by that cap is moved to batteries on healthy phases with
remaining capacity, following the normal SOC/energy priority order.

The envelope is applied to normal PD and direct-tracking control, predictive grid
charging, automatic time-slot PD, active-balance rebalances and the final common
automatic command guard. The assigned total is fed back into the controller so a
phase cap does not create integral windup.

If a phase sensor is missing, unavailable, non-numeric, in the wrong unit or older
than 65 seconds, batteries assigned to that phase receive 0 W. Other healthy
phases continue operating. Sensor recovery is picked up on the next report.

## Important limitations

Manual register writes and manual time-slot commands intentionally remain direct
and can bypass this software envelope. Home Assistant shows a Repairs warning
while the feature is enabled; keep those commands within the electrical limit.

This is a conservative active-power guard, not a replacement for breakers,
inverter protection or an electrician's design. Active W does not translate exactly
to amps or VA when voltage or power factor is not one. Leave margin for measurement
latency, actuator latency, external loads, voltage, power factor, harmonics and
transient peaks: an external load can exceed a phase limit by itself, while
Omnibattery can only avoid making that excess worse. The global controller does not
issue simultaneous charge on one phase and discharge on another. The sensors must
be installed and mapped to the actual conductors; an incorrect L1/L2/L3 assignment
cannot be detected automatically.
