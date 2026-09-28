# Validación del tablero Power BI

Validación ejecutada el 25/09/2026 con Power BI Desktop 2.157, conectando consultas DAX al motor local del modelo
(consultas en [validacion/](validacion/)) y comparando con los resultados del pipeline SQL
(`seccion_2/resultados/2_3_resultado_pipeline.csv`) y con cálculos independientes en pandas.

> **Nota sobre las cifras.** Esta validación se hizo con los datos generados con corte 24/09/2026. Desde el 27/09/2026
> los datos y las consultas usan siempre como corte el día anterior a la ejecución (ayer), por lo que las cifras de las
> tablas siguientes cambian cada vez que se regeneran los datos. Lo que se validó es la lógica: las medidas y el SQL
> usan las mismas reglas, y al actualizar el modelo con datos nuevos deben volver a coincidir. Para repetirla, ejecute
> las consultas de [validacion/](validacion/) sobre el modelo actualizado.

## 1. Conciliación de medidas

| Verificación | Resultado |
|---|---|
| Las 79 medidas evalúan sin error | OK (tras corregir 6 medidas que usaban otra medida dentro de un filtro booleano de CALCULATE) |
| Casos del mes por cliente activo (106 clientes, sep-2026 al 24/09) vs SQL 2.3 | 106/106 idénticos |
| Casos del mes anterior al mismo corte vs SQL 2.3 | 106/106 idénticos |
| Trabajadores activos del mes vs SQL 2.3 | 106/106 idénticos |
| Tasa del mes vs SQL 2.3 | 106/106 (una diferencia de redondeo: 1,145 vs 1,15) |
| Clasificación (crítico / moderado / bajo) | 2 / 28 / 76 en ambos |
| Actividades de prevención 30 días | 106/106 idénticos |
| Casos 90 días y días sin prevención vs consulta 2.2 | 15/15 idénticos |
| Casos y trabajadores-mes por periodo (33 meses) vs pandas | 33/33 idénticos |
| Mes cerrado (ago-2026): casos 350 vs jul 344; tasa 1,82 vs 1,79 | Igual a pandas |
| Casos YTD 2026 | 2.643 (válidos) vs 2.729 con la Medida A literal (incluye anulados) |
| Primer mes de la historia (ene-2024) | C literal = +362 (engañoso); C corregida = en blanco; texto "Sin dato del mes anterior" |

## 2. Seguridad por filas (RLS)

| Prueba | Resultado |
|---|---|
| Rol Gerencia | 120 clientes, 10.117 casos |
| Rol Coordinador con un usuario sin asignación | 0 clientes (no ve nada, no ve todo) |
| Expresión del rol con `coordinador03@…` | 11 clientes, 1.061 casos = pandas |
| Expresión del rol con `COORDINADOR07@…` (mayúsculas) | 8 clientes, 578 casos = pandas |

El motor local de Desktop no permite suplantar usuarios (`EffectiveUserName`) desde una conexión externa; por eso el caso
positivo se probó evaluando la misma expresión del rol con el correo literal. En Desktop se puede repetir con
*Modelado › Ver como › Coordinador + Otro usuario*.

## 3. Revisión visual

Las 6 páginas se abrieron, actualizaron y capturaron en Desktop; se corrigieron: formato de costo con unidades
duplicadas, títulos con barra de desplazamiento, filas de total sin sentido en tablas con texto, columnas cortadas,
etiquetas de referencia que tapaban barras (pasaron a subtítulos) y separador decimal en textos generados con FORMAT.

## Pendientes conocidos

- El botón **Borrar filtros** usa la acción nativa "Borrar todas las segmentaciones"; no se probó con clics automatizados.
- El `.pbix` no se generó automáticamente: se entrega el proyecto PBIP (se guarda como .pbix desde Desktop en un paso).
