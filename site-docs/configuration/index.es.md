# Configuración

La integración se configura mediante dos interfaces:

- La interfaz de Home Assistant, a través de un asistente de varios pasos.
- El dashboard de Omnibattery.

## Configuración del asistente de Home Assistant

```mermaid
flowchart TD
    A[1. Config. del sensor principal] --> B[2. Número de baterías]
    B --> C[3. Config. por batería]
    C --> D{¿Franjas horarias?}
    D -- Sí --> E[4. Franjas horarias]
    D -- No --> F
    E --> F{¿Dispositivos excluidos?}
    F -- Sí --> G[5. Dispositivos excluidos]
    F -- No --> H
    G --> H{¿Carga predictiva?}
    H -- Sí --> I[6. Modo de carga predictiva]
    H -- No --> J
    I --> J
    J[Fin]
```

| Sección | Descripción | Obligatorio |
|------|-------------|:-----------:|
| [Sensores](main-sensor.md) | Sensor de consumo de red y sensor solar (el consumo del hogar se deriva) | ✅ |
| Baterías | Número de unidades | ✅ |
| [Baterías](batteries.md) | Configuración por batería: nombre, IP, puerto, versión, límites de potencia y SOC | ✅ |
| [Franjas horarias](time-slots.md) | Ventanas de descarga/carga con parámetros por franja | ❌ |
| [Dispositivos excluidos](excluded-devices.md) | Cargas pesadas a ignorar | ❌ |
| [Carga predictiva](predictive-charging/index.md) | Carga desde la red cuando la previsión solar es insuficiente | ❌ |
| [Carga semanal completa](advanced.md) | Carga las baterías al 100% una vez a la semana para equilibrar las celdas | ❌ |
| [Retraso de carga solar](advanced.md) | Evita cargar las baterías por la mañana si la producción solar prevista será suficiente | ❌ |
| [Protección de capacidad](advanced.md) | Reserva una parte de la capacidad de batería para picos de demanda (peak shaving) | ❌ |
| [Balance neto horario](advanced.md) | Establece el balance neto de importación/exportación horario a un objetivo específico (por defecto 0 Wh) | ❌ |
| [Límites de potencia del sistema](batteries.md#limites-de-potencia-del-sistema-todas-las-baterias-combinadas) | Limita la potencia combinada de carga/descarga de todas las baterías activas | ❌ |
| [Controlador PD (avanzado)](advanced.md) | Ajuste fino del controlador PD para mantener el flujo de red en el objetivo configurado | ❌ |

## Modificar la configuración

Una vez instalada, puedes modificar cualquier parámetro en:
**Ajustes → Dispositivos y servicios → Omnibattery → Configurar**

![Reconfigurar Omnibattery](../assets/screenshots/configuration/reconfigure-omnibattery.png){ width="650" style="display: block; margin: 0 auto;"}
