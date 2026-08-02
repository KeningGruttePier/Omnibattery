# Hoymiles MS-A2

La Hoymiles MS-A2 se comunica con Omnibattery mediante la integración MQTT ya
configurada en Home Assistant. Omnibattery no necesita el host, puerto ni
credenciales del broker; Home Assistant gestiona la conexión MQTT.

## Requisitos previos

Antes de añadir la batería:

- pon en marcha la MS-A2 en **S-Miles Home**;
- usa un firmware que exponga **Servicio MQTT**;
- configura un broker MQTT local mediante Home Assistant;
- asegúrate de que la MS-A2 puede alcanzar el broker;
- anota el ID MQTT completo, normalmente similar a `MSA-280024341346`.

La [guía completa de instalación de Hoymiles](../hoymiles-ms-a2.md) cubre la
instalación eléctrica, S-Miles Home, MQTT y las comprobaciones finales.

## Conexión

Selecciona **Hoymiles MS-A2** como marca e introduce solo un nombre descriptivo
y el ID MQTT completo. La prueba de conexión escucha la telemetría en tiempo
real a través de Home Assistant.

| Campo | Descripción |
|---|---|
| **Nombre** | Nombre usado para el dispositivo de batería |
| **ID de dispositivo MQTT** | ID completo de la MS-A2, incluido el prefijo `MSA-` |

No hacen falta una dirección IP, un puerto HTTP, sensores MQTT ni automatizaciones
MQTT manuales.

## Capacidad y límites

Una MS-A2 individual tiene una capacidad nominal de `2,24 kWh`; un sistema
emparejado compatible usa normalmente `4,48 kWh`. Introduce la capacidad
nominal aplicable en el paso de límites.

La envolvente de potencia se detecta por MQTT y está limitada a `2000 W`; una
unidad independiente suele estar limitada a `1000 W` en ambos sentidos. Los
límites comunes también incluyen SOC máximo, SOC mínimo e histéresis de carga.
El SOC mínimo predeterminado es `10 %`.

El protocolo MQTT no expone límites de SOC editables ni tensiones de celda
individuales. Por ello Omnibattery aplica los límites de SOC por software y las
funciones de equilibrio de celdas y reducción por tensión de Marstek no están
disponibles para la MS-A2.

Para los controles en tiempo de ejecución y los límites del sistema, consulta
la [configuración de baterías](index.md).
