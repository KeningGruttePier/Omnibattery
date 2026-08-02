# Script MQTT para Shelly Pro 3EM

Un Shelly Pro 3EM no ofrece de forma nativa una cadencia de telemetría MQTT de 1–2 segundos. Este script se ejecuta en el dispositivo y publica la telemetría cada segundo para un Pro 3EM configurado con tres contadores monofásicos. También publica la configuración MQTT Discovery de Home Assistant para los sensores.

!!! warning "Ámbito"
    Usa este script con un Shelly Pro 3EM configurado en el perfil de tres contadores monofásicos. Lee `EM1.GetStatus` para los canales `0`, `1` y `2`, y expone cada canal como una pinza independiente.

## Requisitos

- MQTT activado y conectado en el dispositivo Shelly.
- Home Assistant conectado al mismo broker MQTT.
- MQTT Discovery activado en Home Assistant (el prefijo predeterminado es `homeassistant`).

## Instalación

1. Abre la interfaz web de Shelly y entra en **Scripts**.
2. Crea un script nuevo y pega el código siguiente.
3. Guarda el script y, después, actívalo y ejecútalo.
4. Selecciona el sensor de potencia de red descubierto al configurar el [sensor principal](../configuration/main-sensor.md) de Omnibattery.

El script publica el estado en `shellypro3em/<device-id>/state` y la disponibilidad en `shellypro3em/<device-id>/availability`. El broker MQTT conserva los mensajes de descubrimiento; el estado se publica una vez por segundo.

## Script

```javascript
// Shelly Pro 3EM in three single-phase meters profile
// MQTT telemetry + Home Assistant MQTT Discovery.
//
// Publishes every second:
// - Active power, voltage, current, and power factor per clamp
// - Total active power calculated from all three clamps
//
// Requirements:
// - MQTT enabled and connected on the Shelly device
// - Home Assistant connected to the same MQTT broker
// - MQTT Discovery enabled in Home Assistant (default prefix: homeassistant)

let DISCOVERY_PREFIX = "homeassistant";
let STATE_INTERVAL_MS = 1000;
let STATE_EXPIRE_AFTER_S = 5;

let dev = Shelly.getDeviceInfo();
let DEVICE_ID = dev.id || "shellypro3em";
let DEVICE_NAME = dev.name || "Shelly Pro 3EM";

let BASE_TOPIC = "shellypro3em/" + DEVICE_ID;
let STATE_TOPIC = BASE_TOPIC + "/state";
let AVAILABILITY_TOPIC = BASE_TOPIC + "/availability";

let lastAvailability = null;
let publishing = false;

function haConfigTopic(objectId) {
  return DISCOVERY_PREFIX + "/sensor/" + DEVICE_ID + "_" + objectId + "/config";
}

function setAvailability(online) {
  if (lastAvailability === online) return;

  lastAvailability = online;
  MQTT.publish(
    AVAILABILITY_TOPIC,
    online ? "online" : "offline",
    0,
    true
  );
}

function publishDiscoverySensor(
  objectId,
  name,
  unit,
  deviceClass,
  stateClass,
  valueTemplate
) {
  let payload = {
    name: name,
    unique_id: DEVICE_ID + "_" + objectId,
    object_id: DEVICE_ID + "_" + objectId,

    state_topic: STATE_TOPIC,
    value_template: valueTemplate,
    expire_after: STATE_EXPIRE_AFTER_S,

    availability_topic: AVAILABILITY_TOPIC,
    payload_available: "online",
    payload_not_available: "offline",

    unit_of_measurement: unit,
    device_class: deviceClass,
    state_class: stateClass,
    force_update: false,

    device: {
      identifiers: [DEVICE_ID],
      name: DEVICE_NAME,
      manufacturer: "Shelly",
      model: "Shelly Pro 3EM",
      sw_version: dev.fw_id || ""
    }
  };

  // Retained: Home Assistant can recreate the entities after a restart.
  MQTT.publish(haConfigTopic(objectId), JSON.stringify(payload), 0, true);
}

function publishDiscovery() {
  // Total active power
  publishDiscoverySensor(
    "total_active_power",
    "Total Active Power",
    "W",
    "power",
    "measurement",
    "{{ value_json.total_act_power | float(0) }}"
  );

  // Clamp 1
  publishDiscoverySensor(
    "clamp_1_active_power",
    "Clamp 1 Active Power",
    "W", "power", "measurement",
    "{{ value_json.clamp_1.act_power | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_1_voltage",
    "Clamp 1 Voltage",
    "V", "voltage", "measurement",
    "{{ value_json.clamp_1.voltage | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_1_current",
    "Clamp 1 Current",
    "A", "current", "measurement",
    "{{ value_json.clamp_1.current | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_1_power_factor",
    "Clamp 1 Power Factor",
    "", "power_factor", "measurement",
    "{{ value_json.clamp_1.pf | float(0) }}"
  );

  // Clamp 2
  publishDiscoverySensor(
    "clamp_2_active_power",
    "Clamp 2 Active Power",
    "W", "power", "measurement",
    "{{ value_json.clamp_2.act_power | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_2_voltage",
    "Clamp 2 Voltage",
    "V", "voltage", "measurement",
    "{{ value_json.clamp_2.voltage | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_2_current",
    "Clamp 2 Current",
    "A", "current", "measurement",
    "{{ value_json.clamp_2.current | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_2_power_factor",
    "Clamp 2 Power Factor",
    "", "power_factor", "measurement",
    "{{ value_json.clamp_2.pf | float(0) }}"
  );

  // Clamp 3
  publishDiscoverySensor(
    "clamp_3_active_power",
    "Clamp 3 Active Power",
    "W", "power", "measurement",
    "{{ value_json.clamp_3.act_power | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_3_voltage",
    "Clamp 3 Voltage",
    "V", "voltage", "measurement",
    "{{ value_json.clamp_3.voltage | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_3_current",
    "Clamp 3 Current",
    "A", "current", "measurement",
    "{{ value_json.clamp_3.current | float(0) }}"
  );
  publishDiscoverySensor(
    "clamp_3_power_factor",
    "Clamp 3 Power Factor",
    "", "power_factor", "measurement",
    "{{ value_json.clamp_3.pf | float(0) }}"
  );
}

function publishState() {
  // Prevent overlapping asynchronous requests.
  if (publishing) return;
  publishing = true;

  Shelly.call("EM1.GetStatus", { id: 0 }, function (c1, err1, msg1) {
    if (err1 !== 0) {
      print("EM1:0 error:", err1, msg1);
      setAvailability(false);
      publishing = false;
      return;
    }

    Shelly.call("EM1.GetStatus", { id: 1 }, function (c2, err2, msg2) {
      if (err2 !== 0) {
        print("EM1:1 error:", err2, msg2);
        setAvailability(false);
        publishing = false;
        return;
      }

      Shelly.call("EM1.GetStatus", { id: 2 }, function (c3, err3, msg3) {
        if (err3 !== 0) {
          print("EM1:2 error:", err3, msg3);
          setAvailability(false);
          publishing = false;
          return;
        }

        let p1 = c1.act_power || 0;
        let p2 = c2.act_power || 0;
        let p3 = c3.act_power || 0;

        let payload = {
          total_act_power: p1 + p2 + p3,

          clamp_1: {
            act_power: c1.act_power,
            aprt_power: c1.aprt_power,
            current: c1.current,
            voltage: c1.voltage,
            pf: c1.pf,
            freq: c1.freq
          },

          clamp_2: {
            act_power: c2.act_power,
            aprt_power: c2.aprt_power,
            current: c2.current,
            voltage: c2.voltage,
            pf: c2.pf,
            freq: c2.freq
          },

          clamp_3: {
            act_power: c3.act_power,
            aprt_power: c3.aprt_power,
            current: c3.current,
            voltage: c3.voltage,
            pf: c3.pf,
            freq: c3.freq
          }
        };

        setAvailability(true);
        MQTT.publish(STATE_TOPIC, JSON.stringify(payload), 0, false);
        publishing = false;
      });
    });
  });
}

// Publish discovery configuration once on each script start.
// Config messages are retained by the MQTT broker.
publishDiscovery();

// Publish immediately, then every second.
publishState();
Timer.set(STATE_INTERVAL_MS, true, publishState);
```
