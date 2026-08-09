# Baterías Hoymiles mediante MQTT

Las baterías de microalmacenamiento Hoymiles compatibles se comunican con
Omnibattery mediante la integración MQTT ya configurada en Home Assistant.
Omnibattery no necesita el host, puerto ni las credenciales del broker; Home
Assistant gestiona la conexión.

## Modelos compatibles

Omnibattery lee `device.model` y la envolvente de potencia firmada `min`/`max`
del payload MQTT discovery retenido. El perfil detectado aporta la capacidad
nominal y el techo de seguridad específico del modelo; la envolvente anunciada
por el equipo sigue siendo el límite final.

| Modelo MQTT | Producto | Capacidad | Techo de seguridad del perfil¹ |
|---|---|---:|---:|
| `MS-A2`, `MS-A2-FX`, `MS-A2-ZZ` | MS-A2 | 2,24 kWh por unidad, hasta 4,48 kWh | 1000 W por unidad, hasta 2000 W |
| `HB-1920-AC-SV` | HiBattery 1920 AC | 1,92 kWh por unidad, hasta 11,52 kWh | 1000 W por unidad, hasta 6000 W |
| `HB-4020-X`, `HB-4020-XM` | HiBattery 4020 X | 4,02 kWh | 2000 W |
| `HB-4020-AC`, `HB-4020-ACM` | HiBattery 4020 AC | 4,02 kWh | 2000 W |

¹ La envolvente MQTT retenida `min`/`max` es la autoridad final y puede ser
inferior o asimétrica según la variante, el país o el firmware.

Los módulos de expansión de la serie 4020 aumentan la energía almacenada, pero
no el límite de carga/descarga de 2000 W de la unidad principal. Comprueba la
capacidad mostrada en el paso de límites si hay módulos de expansión.

## Requisitos previos

Antes de añadir la batería:

- ponla en marcha en **S-Miles Home**;
- usa un firmware que exponga **Servicio MQTT**;
- configura un broker MQTT local mediante Home Assistant;
- asegúrate de que la batería puede alcanzar el broker;
- anota el ID MQTT completo, normalmente similar a `MSA-280024341346`.

La [guía de instalación de la MS-A2](../hoymiles-ms-a2.md) cubre la
configuración del broker, S-Miles Home y las comprobaciones. Los pasos MQTT
también sirven para los modelos HiBattery compatibles; sigue el manual propio
del producto para la instalación eléctrica.

## Conexión y límites

Selecciona **Hoymiles MQTT** como marca e introduce un nombre descriptivo y el
ID MQTT completo. Deja **Modelo de batería** en **Detección automática** en el
caso normal. Si el firmware publica un modelo incorrecto o genérico, elige el
modelo instalado; la envolvente de potencia MQTT en vivo sigue siendo el límite
final. La prueba de conexión espera la telemetría en tiempo real y el payload
discovery retenido del control de potencia. No hacen falta dirección IP, puerto
HTTP, sensores MQTT ni automatizaciones manuales.

El paso siguiente muestra la capacidad y los límites de carga/descarga
detectados. Siguen siendo techos de software editables y se pueden reducir para
la instalación. Por ejemplo, una 4020 X usa una capacidad de `4,02 kWh` y un
perfil máximo de `2000 W`, en vez de heredar los `2,24 kWh` y `1000 W` de la
MS-A2; se conserva cualquier límite inferior anunciado por ese equipo concreto.

El protocolo MQTT no expone límites de SOC editables ni tensiones de celda
individuales. Por ello Omnibattery aplica los límites de SOC por software y las
funciones de equilibrio de celdas y reducción por tensión específicas de
Marstek no están disponibles.

Las entradas existentes creadas por el antiguo flujo exclusivo para MS-A2 se
corrigen al reconfigurar la conexión Hoymiles: si discovery identifica otro
modelo, solo se sustituyen los antiguos valores predeterminados de `1000 W` y
`2,24 kWh` por los de ese perfil. Selecciona el modelo manualmente durante la
reconfiguración si el firmware antiguo no lo identifica correctamente.

Para los controles en tiempo de ejecución y los límites del sistema, consulta
la [configuración de baterías](index.md).

## Referencias del fabricante

- [Protocolo MQTT de Hoymiles](https://www.hoymiles.com/uploadfile/1/202511/9350aa1077.txt)
- [HiBattery 1920 AC](https://www.hoymiles.com/products/hibattery-1920-ac.html)
- [Ficha técnica HiBattery 4020 X](https://www.hoymiles.com/uploadfile/1/202606/95d670b3a3.pdf)
- [HiBattery 4020 AC](https://www.hoymiles.com/products/hibattery-4020-ac.html)
