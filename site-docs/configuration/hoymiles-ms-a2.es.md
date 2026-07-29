# Instalar y configurar una Hoymiles MS-A2

Esta guía cubre todo el proceso desde la puesta en marcha de la MS-A2 hasta su
control mediante Omnibattery. La batería se comunica localmente usando el broker
MQTT ya configurado en Home Assistant; Omnibattery no necesita credenciales
adicionales del broker.

## Antes de empezar

Necesitas:

- una Hoymiles MS-A2 añadida en **S-Miles Home**;
- firmware de la MS-A2 que muestre **Servicio MQTT** en la aplicación;
- Home Assistant con la integración **MQTT** y un broker operativo;
- Omnibattery instalado y un sensor de potencia de red disponible;
- el ID MQTT de la MS-A2, normalmente similar a `MSA-280024341346`.

!!! warning "Instalación eléctrica"
    Sigue la [guía de instalación oficial de la MS-A2](https://www.hoymiles.com/statics/5/hoymiles/picture/User-Manual_MS_A2_Global_EN_REV1.4.pdf) vigente, las etiquetas del producto y la normativa eléctrica local. Apaga la MS-A2 y aísla el sistema de microinversores/PV antes de modificar conexiones de CA. Esta página no sustituye las instrucciones de seguridad del fabricante.

## 1. Instalar y poner en marcha la batería

1. Comprueba que la MS-A2, el cable plug-and-play y los conectores no presentan
   daños.
2. Instala la unidad en una posición vertical permitida y respeta las
   separaciones, temperaturas y protección ambiental indicadas por Hoymiles.
3. Con el equipo aislado, conecta el sistema de microinversores y el cable de red
   de CA exactamente como muestra la guía oficial.
4. Conecta el cable de red a una toma Schuko admisible y enciende la MS-A2.
5. Añade la batería en **S-Miles Home**, conéctala a una red Wi-Fi de 2,4 GHz y
   comprueba que el SOC y la potencia se actualizan en la aplicación.
6. Instala las actualizaciones de firmware ofrecidas por Hoymiles. Continúa solo
   cuando la aplicación muestre **Servicio MQTT** para la batería.

La MS-A2 está acoplada en CA y tiene una capacidad nominal de `2,24 kWh`. Un
sistema compatible de dos unidades utiliza normalmente `4,48 kWh` como
capacidad nominal en Omnibattery.

## 2. Preparar MQTT en Home Assistant

Si MQTT ya funciona con otros dispositivos, reutiliza el mismo broker.

1. En Home Assistant abre **Ajustes → Dispositivos y servicios**.
2. Comprueba que la integración **MQTT** está configurada y conectada.
3. Crea un usuario específico del broker para la MS-A2 si tu broker permite
   usuarios.
4. Anota la dirección LAN, el puerto y las credenciales del broker. El puerto
   MQTT sin cifrar habitual es `1883`.

!!! danger "No expongas MQTT a Internet"
    Mantén el broker en la red local o detrás de una VPN correctamente
    protegida. No redirijas el puerto `1883` del router hacia Internet.

## 3. Conectar la MS-A2 al broker

En **S-Miles Home**:

1. Abre los ajustes de la MS-A2 y selecciona **Servicio MQTT**.
2. Activa el servicio.
3. Introduce la IP o nombre LAN del broker MQTT, el puerto, el usuario y la
   contraseña.
4. Guarda los cambios y espera a que la MS-A2 vuelva a conectarse.
5. Anota el ID MQTT completo mostrado por la aplicación o el broker. Conserva el
   prefijo `MSA-`.

La MS-A2 debería publicar aproximadamente cada segundo en:

```text
homeassistant/sensor/<device_id>/quick/state
```

Por ejemplo:

```text
homeassistant/sensor/MSA-280024341346/quick/state
```

No necesitas crear sensores MQTT ni automatizaciones manualmente. Omnibattery
se suscribe directamente a través de Home Assistant.

## 4. Añadir la batería a Omnibattery

1. Abre **Ajustes → Dispositivos y servicios → Añadir integración** y selecciona
   **Omnibattery**. Para modificar una instalación existente, abre Omnibattery y
   pulsa **Configurar**.
2. Selecciona el sensor de importación/exportación de red y el número de
   baterías.
3. Elige **Hoymiles MS-A2** como marca.
4. Introduce un nombre descriptivo y el ID MQTT completo.
5. Espera la prueba de conexión. La prueba escucha valores reales de SOC y
   potencia, por lo que puede tardar unos segundos.
6. Configura los límites:

    | Ajuste | Valor inicial recomendado |
    |---|---:|
    | Capacidad nominal, una MS-A2 | `2,24 kWh` |
    | Capacidad nominal, sistema emparejado | `4,48 kWh` |
    | Potencia máxima de carga/descarga | Mantén el límite detectado |
    | SOC máximo | `100 %` |
    | SOC mínimo | `10 %` |
    | Histéresis de carga | `2 %` |

7. Completa el resto del asistente de Omnibattery y comprueba que el dispositivo
   de la batería muestra entidades de SOC, potencia, tensión, temperatura y
   energía diaria.

## Cómo funciona el control

Omnibattery convierte automáticamente su convención de potencia con signo al
protocolo de Hoymiles:

- potencia positiva en Omnibattery carga la batería;
- potencia negativa en Omnibattery descarga la batería;
- cero mantiene la batería en reposo.

Cuando el control está activo, el driver selecciona `mqtt_ctrl` y renueva la
orden aproximadamente cada 30 segundos, variando `1 W` el setpoint repetido
porque los valores idénticos pueden ignorarse. Si una renovación falla, se
reintenta después de 5 segundos. Esto es necesario porque la MS-A2 vuelve a su
lógica interna cuando dejan de llegar órdenes MQTT externas. Al descargar
Omnibattery se envían `0 W` y se restaura `general`.

Omnibattery aplica los límites de SOC por software porque el protocolo MQTT no
expone límites de SOC editables de la MS-A2. El balanceo por tensión de celda y
la reducción de carga por tensión no están disponibles porque el protocolo no
informa de las tensiones individuales.

## Lista de comprobación

Después de configurarla, comprueba lo siguiente:

- el dispositivo de batería de Omnibattery está disponible;
- el SOC coincide con S-Miles Home;
- la carga aparece como potencia positiva en Omnibattery;
- la descarga aparece como potencia negativa;
- la batería sigue una orden manual pequeña de carga, descarga y reposo;
- la telemetría MQTT continúa actualizándose localmente a través del broker;
- los límites de potencia y SOC coinciden con la instalación.

Empieza con poca potencia al verificar el sentido. Detén inmediatamente la
prueba si el sentido observado no coincide con el solicitado.

## Solución de problemas

| Síntoma | Comprobaciones |
|---|---|
| **No se puede conectar** en el asistente | Comprueba que MQTT está conectado en Home Assistant, que el Servicio MQTT de la MS-A2 está activo y que el ID `MSA-…` completo es correcto. |
| La aplicación funciona pero Omnibattery no recibe datos | Revisa la IP, puerto y credenciales del broker en S-Miles Home. El broker debe ser accesible desde la Wi-Fi de la batería. |
| La batería vuelve al control autónomo | Busca desconexiones MQTT o reinicios del broker. Omnibattery debe renovar la orden antes del timeout de un minuto. |
| La potencia queda limitada a 1 kW en un sistema emparejado | Reconfigura la batería después de emparejar ambas unidades para que Omnibattery lea el límite MQTT retenido. Los sistemas MS-A2 compatibles admiten hasta 2 kW. |
| El SOC funciona pero las entidades detalladas tardan | `quick/state` se actualiza aproximadamente cada segundo; tensión, temperatura y energía diaria suelen publicarse cada cinco minutos. |
| Se rechaza el control | Actualiza el firmware, confirma que el ID seleccionado pertenece a la unidad master/independiente y vuelve a conectar su Servicio MQTT. |

## Referencias oficiales

- [Página del producto Hoymiles MS-A2](https://www.hoymiles.com/products/micro-storage.html)
- [Guía de instalación/usuario de la MS-A2](https://www.hoymiles.com/statics/5/hoymiles/picture/User-Manual_MS_A2_Global_EN_REV1.4.pdf)
- [Guía del protocolo MQTT de Hoymiles](https://www.hoymiles.com/uploadfile/1/202511/9350aa1077.txt)
