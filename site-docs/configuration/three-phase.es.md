# Protección de potencia trifásica

La protección trifásica es una envolvente de seguridad opcional para instalaciones en las que las baterías comparten una conexión trifásica. Está **desactivada por defecto** y se configura durante el asistente inicial o desde **Ajustes → Integraciones → Omnibattery → Configurar → Sensores**.

## Configuración

Activa la función y selecciona un sensor de potencia en tiempo real y un límite para cada fase que quieras proteger. Deja ambos campos vacíos para las fases no utilizadas, de modo que una instalación de una o dos fases no necesite valores ficticios para las restantes. Deben ser entidades `sensor` de Home Assistant con unidad `W` o `kW`, usando la misma convención que el sensor global:

- positivo = importación de red
- negativo = exportación a red

El ajuste global **Signo del medidor invertido** se aplica a los medidores de fase configurados y a Grid 0. Configura un límite máximo positivo y simétrico, en vatios, para cada fase configurada. La asignación física (`L1`, `L2` o `L3`) es obligatoria para cada batería; Omnibattery no puede descubrir a qué fase está cableada. Una batería asignada a una fase sin sensor ni límite recibe 0 W mientras la protección está activa.

El sensor global de consumo sigue siendo la señal Grid 0 del controlador. Los sensores de fase son solo envolventes de seguridad: no sustituyen Grid 0 ni cambian el objetivo del controlador PD.

## Funcionamiento

Para cada fase, Omnibattery reconstruye la carga sin batería y calcula ambos presupuestos direccionales:

```text
carga_base = lectura_red - potencia_baterías_de_la_fase
presupuesto_carga = max(0, límite - lectura_red + potencia_baterías_de_la_fase)
presupuesto_descarga = max(0, límite + lectura_red - potencia_baterías_de_la_fase)
```

La potencia de batería usa la convención del controlador (`+` carga, `−` descarga). Primero se ejecutan la selección y el reparto proporcional normales. El resultado se redondea después hacia abajo en pasos de 5 W y se limita de forma independiente por fase. Solo la potencia rechazada por ese límite se mueve a baterías de fases sanas con capacidad disponible, siguiendo la prioridad normal por SOC y energía.

La envolvente se aplica al PD normal y al seguimiento directo, a la carga predictiva desde red, al PD de franjas automáticas, a los reequilibrios y al último guard común de comandos automáticos. El total asignado vuelve al controlador para evitar windup integral cuando una fase está limitada.

Si falta el sensor de una fase configurada, no está disponible, no es numérico, tiene una unidad incorrecta o supera los 65 segundos de antigüedad, las baterías asignadas a esa fase reciben 0 W. Una fase sin configurar también queda limitada a 0 W si se asigna una batería a ella. Las demás fases sanas continúan funcionando.

## Limitaciones importantes

Las escrituras manuales de registros y las franjas manuales siguen siendo directas y pueden saltarse esta envolvente. Home Assistant muestra un aviso de Repairs mientras la función está activa; mantén esos comandos dentro del límite eléctrico.

Es una protección conservadora de potencia activa, no sustituye los magnetotérmicos, las protecciones del inversor ni el diseño de un electricista. Los W activos no se traducen exactamente a amperios o VA cuando la tensión o el factor de potencia no son uno. Deja margen para la latencia de medida y del actuador, cargas externas, tensión, factor de potencia, armónicos y picos transitorios: una carga externa puede superar por sí sola el límite de una fase y Omnibattery solo puede evitar que las baterías agraven el exceso. El controlador global no ordena carga simultánea en una fase y descarga en otra. Los sensores deben estar instalados y asignados a los conductores reales; una asignación L1/L2/L3 incorrecta no puede detectarse automáticamente.
