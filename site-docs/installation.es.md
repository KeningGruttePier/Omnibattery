# Instalación

## Requisitos

### Hardware

La tabla muestra la vía de conexión que usa Omnibattery para cada batería
compatible. Los adaptadores y puentes solo son necesarios cuando se indican.

| Batería / componente | Conexión soportada | Requisito adicional |
|---|---|---|
| **Marstek Venus E/C (v2/v3), Venus A, Venus D** | Modbus TCP; Modbus RTU por USB–RS485; o puente LilyGo RS485/ESPHome *(Venus E v2)* | **Modbus TCP:** Venus E v2 necesita un conversor RS485 → TCP (p. ej. Elfin-EW11); Venus E v3, Venus A y Venus D usan Ethernet nativo. **Modbus RTU:** adaptador USB–RS485. **ESPHome:** el puente LilyGo debe exponer sus entidades requeridas en Home Assistant. |
| **Zendure SolarFlow 2400 AC+, 2400 AC Pro, 1600 AC+, 800 Pro, 800 Plus, 800** | API HTTP local | Mantén **HEMS desactivado** en la aplicación de Zendure. Si está activo, HEMS sobrescribe la consigna manual de potencia de Omnibattery. |
| **Anker SOLIX Solarbank Max AC, 4 E5000 Pro** | Modbus TCP | Activa **Third-Party Control** en la aplicación de Anker. Solo puede conectarse un cliente Modbus a la vez. |
| **Sessy Home Battery** | API HTTP local mediante el dongle de Sessy | El dongle debe ser accesible desde Home Assistant. Introduce su IP/nombre de host, puerto y credenciales; el puerto predeterminado es `80`. |
| **Hoymiles MS-A2** | MQTT mediante la integración MQTT configurada en Home Assistant | Hace falta un broker MQTT local operativo (por ejemplo, Mosquitto; se puede reutilizar uno existente). Activa **MQTT Service** en S-Miles Home y asegúrate de que la batería puede alcanzar el broker. |
| **Sensor de red** | Entidad de Home Assistant | Sensor que mida el consumo total de la red (p. ej. Shelly EM3, Neurio o integración de contador inteligente). |

### Software

- Home Assistant **2024.1.0** o superior
- Solo para **Hoymiles MS-A2**: la integración MQTT de Home Assistant y un broker MQTT local operativo. Omnibattery usa el broker a través de Home Assistant; no instala uno.
- (Opcional) Sensor de previsión solar para la carga predictiva (Solcast, Forecast.Solar, etc.)

### Red

Para Modbus TCP y HTTP local, la batería o el puente debe ser accesible desde
Home Assistant por IP en el mismo segmento de red o mediante enrutamiento. Para
Modbus RTU, conecta el adaptador USB al equipo donde se ejecuta Home Assistant.
Para LilyGo/ESPHome, añade el puente a Home Assistant. En Hoymiles, la MS-A2
debe poder alcanzar el broker MQTT en la red local.

---

## Instalación con HACS (recomendado)

1. Haz clic en el botón para añadir el repositorio a HACS:

    [![Añadir a HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ffunes&repository=Omnibattery&category=integration)

2. Busca **"Omnibattery"** e instala.
3. Reinicia Home Assistant.

![Búsqueda en HACS](assets/screenshots/installation/hacs-search.png){ width="700"  style="display: block; margin: 0 auto;"}

---

## Instalación manual

1. Descarga el zip de la última release desde [GitHub Releases](https://github.com/ffunes/Omnibattery/releases).
2. Extrae la carpeta `omnibattery`.
3. Cópiala en el directorio `custom_components/` de Home Assistant.
4. Reinicia Home Assistant.

---

## Instalación de blueprints

Los blueprints son opcionales y se instalan en la carpeta de configuración de Home Assistant, no dentro de `custom_components/`.

La carpeta de blueprints de tu Home Assistant es:

```text
/config/blueprints/automation/omnibattery/
```

Si accedes a Home Assistant mediante Samba, Studio Code Server o File Editor, la misma ruta suele verse como:

```text
config/blueprints/automation/omnibattery/
```

### Instalación desde la interfaz de Home Assistant

1. Ve a **Ajustes** → **Automatizaciones y escenas** → **Blueprints**.
2. Pulsa **Importar blueprint**.
3. Pega la URL del blueprint que quieras importar, por ejemplo:

    ```text
    https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/different_grid_target_blueprint.yaml
    ```

4. Pulsa **Previsualizar blueprint** y después **Importar blueprint**.
5. Crea una automatización nueva desde el blueprint importado y selecciona tus entidades.

### Instalación manual

1. Crea la carpeta `/config/blueprints/automation/omnibattery/` si no existe.
2. Copia dentro los archivos `.yaml` de la carpeta `blueprints/` de este repositorio.
3. En Home Assistant, ve a **Ajustes** → **Automatizaciones y escenas** → **Blueprints** y pulsa **Recargar blueprints**. Si no aparece la opción, reinicia Home Assistant.
4. Crea una automatización nueva desde el blueprint instalado.

---

## Añadir la integración

Después de instalar y reiniciar:

1. Ve a **Ajustes** → **Dispositivos y servicios**.
2. Pulsa **+ AÑADIR INTEGRACIÓN**.
3. Busca **Omnibattery**.
4. Sigue el [asistente de configuración](configuration/index.md).

![Añadir integración en HA](assets/screenshots/installation/add-integration.png){ width="600"  style="display: block; margin: 0 auto;"}
