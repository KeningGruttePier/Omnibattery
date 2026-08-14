# Sessy Home Battery

Omnibattery se conecta a una Sessy mediante la API HTTP local que expone su
dongle. El soporte de Sessy todavía busca testers, así que comunica cualquier
comportamiento específico del modelo o firmware al pedir ayuda.

## Conexión

El dongle debe ser accesible desde Home Assistant. Introduce el host o IP, el
puerto HTTP y las credenciales impresas en el dongle.

| Campo | Descripción | Por defecto |
|---|---|---|
| **Nombre** | Nombre usado para el dispositivo de batería | — |
| **Host** | IP o nombre de host del dongle Sessy | — |
| **Puerto HTTP** | Puerto de la API local | `80` |
| **Usuario** | Usuario del dongle/API | — |
| **Contraseña** | Contraseña del dongle/API | — |

El asistente prueba la API local antes de continuar. Omnibattery no necesita una
conexión a la nube; mantén la API en la red local.

## Límites y capacidad

Sessy usa límites de hardware asimétricos de `2200 W` para cargar y `1700 W`
para descargar. La integración prepara estos valores, en lugar de pedir límites
de hardware editables durante el asistente.

El asistente exige la capacidad nominal de la batería en kWh (`0,01–100 kWh`),
porque la API de Sessy no ofrece un contador de capacidad nominal. También
configura los límites comunes de SOC, la histéresis de carga y el umbral de
backup offgrid. El SOC mínimo predeterminado es `5 %` y el máximo `100 %`.

Sessy no ofrece la reducción de carga por tensión de celdas de Marstek. Consulta
la [configuración de baterías](index.md) para los controles comunes en tiempo de
ejecución y los límites de potencia del sistema.

### Control manual

La API de Sessy expone una consigna de potencia neta, no registros de modo
forzado como Marstek. Usa `Modo forzado` y los controles de potencia de software
con **Control Manual de Batería** activado; Omnibattery reaplica las consignas
distintas de reposo mediante la API local mientras esa propiedad esté activa.
