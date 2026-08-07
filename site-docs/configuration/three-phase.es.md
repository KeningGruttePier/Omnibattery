# Protección de corriente trifásica

La protección de corriente trifásica es una envolvente de seguridad opcional para instalaciones en las que las baterías comparten una conexión trifásica. Está **desactivada por defecto** y se configura durante el asistente inicial o desde **Ajustes → Integraciones → Omnibattery → Configurar → Sensores**.

## Configuración

Activa la función y selecciona un sensor de corriente RMS con signo en tiempo real y el tamaño/límite del fusible en amperios para cada fase que quieras proteger. Deja ambos campos vacíos para las fases no utilizadas, de modo que una instalación de una o dos fases no necesite valores ficticios para las restantes. Deben ser entidades `sensor` de Home Assistant con unidad `A` o `mA`, usando la misma convención que el sensor global:

- positivo = importación de red
- negativo = exportación a red

El ajuste global **Signo del medidor invertido** se aplica a los medidores de fase configurados y a Grid 0. Configura un límite positivo y simétrico en amperios para cada fase configurada, preferiblemente inferior al valor nominal del fusible para dejar margen. La asignación física (`L1`, `L2` o `L3`) es obligatoria para cada batería; Omnibattery no puede descubrir a qué fase está cableada. Una batería asignada a una fase sin sensor ni límite funciona normalmente, sin límite de protección de fase.

El sensor global de consumo sigue siendo la señal Grid 0 del controlador. Los sensores de fase son solo envolventes de seguridad: no sustituyen Grid 0 ni cambian el objetivo del controlador PD.

## Funcionamiento

Para cada fase, Omnibattery reconstruye la corriente sin batería y calcula ambos presupuestos direccionales:

```text
corriente_base = corriente_de_fase - corriente_de_baterías_de_la_fase
corriente_batería_mínima = max(-tamaño_fusible, -tamaño_fusible - corriente_base)
corriente_batería_máxima = min(+tamaño_fusible, +tamaño_fusible - corriente_base)
presupuesto_carga_corriente = max(0, corriente_batería_máxima)
presupuesto_descarga_corriente = max(0, -corriente_batería_mínima)
```

El sensor de corriente debe incluir el signo: positivo significa importación y negativo exportación. La telemetría y los comandos de las baterías usan la convención del controlador (`+` carga, `−` descarga) y siguen expresándose en vatios activos. Internamente, la restricción del contador y la restricción absoluta de la orden de batería se intersectan como un intervalo con signo antes de convertir los presupuestos direccionales a vatios. Los vatios de batería se convierten a corriente y el presupuesto disponible se convierte de nuevo a un límite conservador en vatios usando 230 V nominales y un factor de potencia de 0,90. Primero se ejecutan la selección y el reparto proporcional normales. El resultado se redondea después hacia abajo en pasos de 5 W y se limita de forma independiente por fase. Solo la potencia rechazada por ese límite se mueve a baterías de fases sanas con capacidad disponible, siguiendo la prioridad normal por SOC y energía.

El límite configurado es un tope absoluto por fase para las órdenes automáticas de batería en ambos sentidos. La corriente base reconstruida puede reducir el presupuesto disponible, pero nunca aumentarlo por encima del límite configurado. El contador de una fase aún puede superar el límite por una carga externa, latencia de medida/actuación o una orden manual; la protección automática no puede eliminar una carga externa.

La envolvente se aplica al PD normal y al seguimiento directo, a la carga predictiva desde red, al PD de franjas automáticas, a los reequilibrios y al último guard común de comandos automáticos. El total asignado vuelve al controlador para evitar windup integral cuando una fase está limitada.

Si falta el sensor de una fase configurada, no está disponible, no es numérico, tiene una unidad incorrecta o supera los 65 segundos de antigüedad, las baterías asignadas a esa fase reciben 0 W. El sensor debe incluir signo; un sensor de corriente sin signo no puede representar correctamente la exportación y no debe usarse con esta función. Una fase sin configurar no tiene protección de fase, por lo que las baterías asignadas a ella siguen funcionando con los límites normales del controlador y de cada batería. Las demás fases sanas continúan funcionando.

## Limitaciones importantes

Las escrituras manuales de registros y las franjas manuales siguen siendo directas y pueden saltarse esta envolvente. Home Assistant muestra un aviso de Repairs mientras la función está activa; mantén esos comandos dentro del límite eléctrico.

Es una protección conservadora de corriente, no sustituye los magnetotérmicos, las protecciones del inversor ni el diseño de un electricista. Usa un sensor RMS real con un signo fiable de importación/exportación y deja margen por debajo del valor nominal del fusible para la latencia de medida y del actuador, cargas externas, tensión, factor de potencia, armónicos y picos transitorios. La conversión interna de 230 V/0,90 es una estimación para traducir los comandos de batería en vatios a un presupuesto de corriente RMS; el sensor de corriente sigue siendo la medida de seguridad de la fase. Una carga externa puede superar por sí sola el límite de una fase y Omnibattery solo puede evitar que las baterías agraven el exceso. El controlador global no ordena carga simultánea en una fase y descarga en otra. Los sensores deben estar instalados y asignados a los conductores reales; una asignación L1/L2/L3 incorrecta no puede detectarse automáticamente.

El esquema beta usa campos de sensor de corriente y tamaño del fusible. No hay migración intencionada desde los campos anteriores de potencia por fase, por lo que hay que volver a introducir la configuración de protección de fase después de actualizar.
