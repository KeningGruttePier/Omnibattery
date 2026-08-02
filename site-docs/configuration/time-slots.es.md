# Franjas horarias

Las franjas horarias definen ventanas que controlan cómo se permite operar a cada batería. Cada franja expone ticks independientes para carga y descarga, overrides opcionales de SOC y de potencia, un modo manual y un alcance por batería. Se admiten hasta 8 franjas.

![Time slot configuration](../assets/screenshots/configuration/time-slot-form.png){ width="600"  style="display: block; margin: 0 auto;"}

## Modelo: whitelist por dirección

Cada dirección (carga, descarga) se evalúa de forma independiente:

- Si **ninguna franja permite la dirección X** para una batería dada, la dirección X queda sin restricciones (el resto del controlador — SOC máx/mín, pausa por VE, etc. — sigue aplicándose).
- Si **al menos una franja permite la dirección X**, esa dirección sólo está autorizada dentro de una franja activa con `allow_X=True`, día coincidente y alcance aplicable. Fuera de cualquier franja activa la dirección queda bloqueada.

Esto preserva el comportamiento anterior: las "franjas de no-descarga" existentes siguen siendo un whitelist de descarga tras la migración, y el flag legado `apply_to_charge` se mapea a `allow_charge=True`.

## Campos de la franja

| Campo | Descripción |
|---|---|
| **Hora inicio / fin** | Ventana (p. ej. `14:00` – `18:00`). Se admite cruce de medianoche (`start > end` ⇒ ventana atraviesa las 00:00). |
| **Días** | Días de la semana en los que aplica. |
| **Alcance de batería** | `all` para aplicar a todas, o `battery_N` para una concreta. |
| **Permitir carga** | Tick: la carga está permitida dentro de la franja. Activa el whitelist de carga si alguna franja lo usa. |
| **Permitir descarga** | Tick: la descarga está permitida dentro de la franja. Activa el whitelist de descarga si alguna franja lo usa. |
| **Override SOC (tick + `soc_min` / `soc_max`)** | Si el tick está activado, la franja sustituye al SOC máx/mín de la batería dentro de la ventana. Limitado a `[12, 100]`. |
| **Override potencia (tick + `max_charge_power_w` / `max_discharge_power_w`)** | Si el tick está activado, la franja limita la potencia dinámica PD o fija la potencia exacta manual. |
| **Modo** | `pd`: el algoritmo predictivo regula dentro de los topes de la franja. `manual`: la batería se fuerza a la potencia configurada (una sola dirección). |

## Comportamiento por modo

- **Modo PD (por defecto)**: la franja actúa como restricción. Los overrides de SOC y potencia se aplican sobre el lazo PD normal; el controlador sigue respondiendo a red y consumo.
- **Modo Manual**: requiere el tick de potencia activo y exactamente una de `allow_charge` / `allow_discharge` activada. La batería se fuerza a esa potencia exacta (force charge o force discharge) y se excluye de la asignación PD durante el ciclo. Los blockers de seguridad (SOC mín, SOC máx, pausa VE, balance activo) siguen deteniendo la escritura manual.

## Alcance por batería

Con varias baterías cada franja elige su destinatario con `battery_scope`. Franjas con alcances distintos pueden solaparse en tiempo sin conflicto — sólo entran en conflicto si ambas apuntan a la misma batería física (`battery_N` vs `battery_N`, o cualquiera de las dos a `all`).

## Diagnóstico

La entidad `binary_sensor.predictive_charging_active` expone dos atributos del ciclo actual:

- `active_slot_per_battery`: dict (por nombre de batería) con la franja activa: inicio/fin, alcance, ticks, modo y valores de override.
- `manual_slot_owned`: lista de baterías cuyo control ha tomado una franja manual en el ciclo.

## Límites

- Máximo 8 franjas por integración.
- El override de SOC se aplica por software; espera 1–3 ciclos de control (unos segundos, a la cadencia del sensor de red) hasta que la carga o descarga se detenga al límite del slot.
- Las franjas que apuntan a un `battery_N` inexistente (p. ej. tras reducir el número de baterías) quedan inertes; edítalas o bórralas desde el menú de opciones.
