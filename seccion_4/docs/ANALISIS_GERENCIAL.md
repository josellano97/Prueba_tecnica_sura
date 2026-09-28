# Análisis gerencial · diseño, decisiones y hallazgos

Capa de apoyo a la decisión construida sobre la aplicación Django (`apps/analisis`). No reemplaza el tablero de
monitoreo: lo complementa con las preguntas que un gerente se hace después de ver un número. **¿Es normal? ¿Por
qué cambió? ¿Dónde está? ¿Desde cuándo? ¿Qué tan importante es? ¿Qué reviso primero?**

Todas las cifras de este documento provienen de la fuente oficial del proyecto (`datos/salida`, la misma del SQL de
la Sección 2 y del Power BI de la Sección 1), generada con **fecha de corte 26/09/2026**. Los datos se generan siempre
con corte = ayer, así que las cifras cambian cada vez que se regeneran; la app muestra siempre las de la última carga.
Se recalcularon de forma independiente con pandas (`herramientas/validar_analisis.py`, 23/23 coincidencias).

---

## 1. Descubrimiento de los datos (fase 1)

| Archivo | Registros | Grano | Uso en el análisis |
|---|---:|---|---|
| clientes.csv | 120 | cliente | sector, clase de riesgo 1–5, coordinador, fecha de vinculación, estado |
| coordinadores.csv | 12 | coordinador | nombre y regional |
| facturacion.csv | 3.385 | cliente × mes | **exposición** (trabajadores activos) y valor de contrato |
| casos.csv | 10.411 | caso | fecha, tipo leve/grave, días de ausencia, costo, estado (abierto/cerrado/anulado) |
| prevencion.csv | 5.690 | actividad | fecha, cliente y participantes |
| trabajadores.csv | — | — | no se usa: la exposición oficial es la de facturación (misma decisión que el SQL) |

- **Periodo:** desde el 1 de enero de dos años antes hasta la fecha de corte (hoy: enero 2024 a 26/09/2026). El mes
  del corte está incompleto y se excluye; **el último mes analizado es el anterior** (agosto 2026: 322 casos,
  19.347 trabajadores, tasa 1,66).
- **Granularidad elegida: mensual.** La exposición solo existe por mes (se factura por mes). Una tasa diaria o
  semanal no tendría denominador, y con unos 10 casos por día en toda la cartera sería ruido.
- **Dimensiones disponibles:** tiempo, sector, clase de riesgo, regional, coordinador, cliente y caso.
- **Qué NO trae la fuente:** metas, presupuesto, horas trabajadas, causa del caso, fecha de cierre y tipo o
  efectividad de la actividad de prevención. Ver la sección 7.

### Calidad de datos (se muestra en la app, página *Calidad de datos*)

| Hallazgo | Cantidad | Tratamiento |
|---|---:|---|
| Mes en curso incompleto (facturación de 09/2026) | 106 registros | Excluido de los indicadores mensuales |
| Casos anulados | 295 | No son incidentes: se excluyen de todo indicador |
| Casos del mes en curso | 284 | Fuera de los indicadores mensuales |
| Tipo que no concuerda con los días (grave con ≤ 15 días o leve con > 15) | 529 | Se respeta el campo oficial `tipo`. Los días se usan solo para severidad. **Validar la regla con el área dueña** |
| Costo atípico (mayor a Q3 + 3·IQR de su tipo) | 77 | Se conservan (son válidos), pero pesan en el costo |
| Sin metas ni presupuesto | — | Indicadores descriptivos, sin "% de cumplimiento" |

El cargador también valida clientes inválidos o sin coordinador, facturación inconsistente, casos duplicados, sin
cliente, con fecha o valores inválidos, sin exposición ese mes y actividades de prevención inválidas. En esta
fuente esos controles no encontraron registros. Resultado: 9.832 casos válidos en los indicadores y 3.279 registros
cliente × mes.

Observación a validar: el costo de los casos equivale a entre 110 y 236 por cada 100 facturados. Sin saber si
`valor_contrato` es mensual, anual o una prima, ese cociente **no** se presenta como rentabilidad.

## 2. Preguntas de negocio (fase 2)

| Pregunta del gerente | Dónde se responde |
|---|---|
| ¿Cómo estamos este mes? ¿Es normal? | Resumen ejecutivo (máximo 4 hechos) y KPI de nivel 1, con prueba de significancia |
| ¿Qué cambió y por qué? | "¿Por qué cambió?": el usuario elige el mes, el periodo (mes, 3 meses, año corrido, 12 meses), la comparación (periodo anterior o mismo periodo del año anterior), la dimensión (sector, clase, regional, coordinador, cliente) y la medida (casos o costo). Descomposiciones exactas y contribución de cada miembro |
| ¿Desde cuándo? ¿Es tendencia o un mes aislado? | Serie de 24 meses con meses anómalos marcados y pendiente de 12 meses |
| ¿Dónde se concentra? | Tres bloques: concentración del costo por cliente, sectores fuera de lo esperable por su riesgo y peso de los casos graves en el costo; las tablas completas quedan plegadas |
| ¿Qué reviso primero? | "Qué debería revisar": solo alertas de prioridad alta, una línea cada una, ordenadas por casos en exceso |
| ¿Quién tiene problemas repetidos? | Clientes críticos recurrentes y clientes en riesgo sin prevención |
| ¿Puedo llegar al caso concreto? | Diagnóstico: total → dimensión → cliente → mes → caso |
| ¿Puedo confiar en los datos? | Calidad de datos y metodología |

## 3. Jerarquía de KPI (fase 3)

La definición completa (fórmula, fuente, interpretación, sentido, limitaciones y disponibilidad según la fuente
cargada) está en la app, en *Metodología y KPIs*, y en código en `apps/analisis/servicios/kpis.py`. Ningún KPI
requiere datos que la fuente no tenga. Si una variable falta (p. ej. con los datos demo), el KPI se oculta y se
informa.

**Nivel 1 · ejecutivos** (¿cómo estamos?)

| KPI | Fórmula | Mejor si |
|---|---|---|
| Tasa de incidencia | casos ÷ trabajadores activos × 100 (definición oficial de la prueba) | baja |
| Casos | casos válidos (sin anulados) | baja |
| Costo de los casos | Σ costo de casos válidos | baja |
| Días perdidos por 100 trabajadores (severidad) | Σ días de ausencia ÷ trabajadores × 100 | baja |
| Clientes en estado crítico | clientes con tasa > umbral crítico (regla oficial 2.3, configurable) | baja |
| Cobertura de prevención | clientes con ≥ 1 actividad en el mes ÷ clientes facturados | sube |

**Nivel 2 · explicativos** (¿por qué se mueve el nivel 1?): trabajadores (exposición), % de casos graves, costo por
caso, % del costo en graves, días por caso, actividades de prevención por 100 trabajadores, % de trabajadores en
clientes críticos, costo por cada $100 facturados (solo descriptivo) y casos graves abiertos. Este último es una
foto a la fecha de corte y no se compara entre meses.

**Nivel 3 · diagnóstico:** los mismos indicadores abiertos por sector, clase de riesgo, regional, coordinador,
cliente, mes y caso individual.

Periodicidad: mensual (mes cerrado). Referencias: el mes anterior, el mismo mes del año anterior (controla la
estacionalidad), los 12 meses previos agregados y el acumulado del año contra el mismo periodo del año anterior.

## 4. Métodos analíticos (fases 4 y 5) y por qué se eligieron

| Necesidad | Método | Por qué este y no otro |
|---|---|---|
| ¿La diferencia es real o azar? | Prueba de Poisson exacta: casos observados vs esperables (exposición actual × tasa de referencia) | Los casos son conteos: un % de variación sin prueba exagera en clientes pequeños |
| ¿Es significativa para KPI sin prueba? | Distancia de 2 desviaciones estándar respecto de la variación de los 12 meses previos | Sustituye un umbral arbitrario (p. ej. "±15 %") por la variabilidad propia del KPI |
| ¿Hay tendencia? | Regresión lineal de 12 meses; se afirma solo si \|t\| ≥ 2 | Evita llamar "tendencia" a dos meses seguidos |
| ¿Por qué cambiaron los casos? | Casos = exposición × tasa (efecto exposición + efecto tasa) | Distingue "más trabajadores" de "más riesgo". Los efectos suman exactamente la variación |
| ¿Por qué cambió la tasa? | Mezcla de clases + cambio dentro de cada clase | Una cartera con más clase 5 sube la tasa sin que nadie empeore |
| ¿Por qué cambió el costo? | Casos × costo por caso | Separa frecuencia de gravedad o costo unitario |
| ¿Un sector tiene más casos de lo que explica su riesgo? | Razón estandarizada por clase (observados ÷ esperables con la tasa de la cartera por clase), con prueba de Poisson | Comparar sectores sin ajustar culpa a los que tienen actividades más riesgosas |
| Clientes pequeños | Tasa de referencia ajustada hacia la de su clase (300 trabajadores-mes), igual que el SQL 2.2 | Un solo caso en un cliente de 20 trabajadores no debe disparar una alerta |
| Prevención | Tasa de clientes-mes con y sin prevención, estratificada por clase (mínimo 500 trabajadores-mes por grupo) | Evita que la clase de riesgo confunda la comparación. Se presenta como **asociación**, no como efecto |
| Priorizar | Alertas ordenadas por **casos en exceso** sobre lo esperable; en el resumen solo las de prioridad alta (p < 0,1 % o regla oficial) | Una sola escala comparable entre alertas de distinto tipo, y pocas cosas en pantalla |

**Comparaciones múltiples:** cada mes se prueban unos 100 clientes. Al 1 % se espera, por azar, cerca de un falso
positivo mensual. Por eso la alerta de un cliente individual es de prioridad media salvo que p < 0,1 %, y se
recomienda confirmarla con el coordinador.

**Texto generado:** cada frase del resumen ejecutivo lleva su etiqueta: *hecho* (dato observado), *hipótesis*
(posible explicación, a validar) o *advertencia* (limitación del dato). Los colores rojo o verde se usan solo cuando
la diferencia es significativa.

## 5. Arquitectura y rendimiento

```
apps/analisis/servicios/
  datos.py          cubo en memoria cliente × mes (respeta el alcance del coordinador y los filtros)
  kpis.py           catálogo: fórmula, agregación (suma / razón / promedio mensual), sentido, limitaciones
  estadistica.py    Poisson exacta, tendencia lineal, niveles de significancia
  comparaciones.py  valor vs referencias, serie, tendencia, juicio (normal / peor / mejor / sin referencia)
  explicacion.py    descomposiciones exactas, contribuciones por dimensión, asociación con prevención
  concentracion.py  Pareto, sobre-representación y razón estandarizada por clase
  anomalias.py      meses y segmentos anómalos, persistencia, recurrencia crítica, brechas de prevención
  alertas.py        construcción y priorización de alertas
  resumen.py        resumen ejecutivo (hechos, hipótesis y advertencias)
  diagnostico.py    tablas del drill-down y perfil del cliente
  faltantes.py      indicadores no construibles y el dato que los habilitaría
  motor.py          orquesta todo y cachea el resultado
```

Las vistas solo validan filtros, aplican permisos y arman el contexto; toda la lógica está en `servicios/` y tiene
pruebas. Los permisos nuevos son `tablero.ver_analisis` y `tablero.ver_calidad_datos`. El alcance del coordinador
se aplica al construir el cubo, así que un coordinador no puede ver clientes ajenos ni por URL. El cálculo se hace
sobre unos 3.300 registros cliente × mes; el resultado se guarda en caché 10 minutos con una clave que incluye la
carga de datos, la configuración, el alcance y los filtros. Una página servida desde la caché responde en unos 60 ms.

## 6. Hallazgos con los datos de la última carga (corte 26/09/2026; mes analizado: agosto 2026)

Hechos:

- **Agosto está dentro de su rango normal:** tasa 1,66 vs 1,68 de sus 12 meses previos, diferencia no significativa.
- **Ningún sector ni cliente** queda significativamente por encima de lo esperable este mes, así que no hay alertas de
  prioridad alta.
- **Concentración del costo:** 33 de 109 clientes explican el 80 % del costo de los últimos 12 meses.
- **Ajustado por clase de riesgo,** Construcción pasa de 1,59 a 1,14 y Agroindustria de 1,35 a 1,19: ambas siguen
  **significativamente por encima** de lo esperable para su riesgo, pero mucho menos de lo que sugiere la cifra sin
  ajustar. Manufactura pasa de 1,21 a 0,91 (por debajo): su exceso lo explica su clase.
- **Meses anómalos en 24 meses:** enero 2025 (caída) y junio 2025 (caída).

Hipótesis:

- Los clientes-mes con prevención muestran una tasa unos 26 % menor dentro de la misma clase de riesgo. Es
  consistente con un efecto protector, pero no lo prueba: los clientes que reciben prevención pueden diferir en otros
  aspectos.

## 7. Oportunidades de mejora · información faltante

También en la app (*Metodología y KPIs › Información faltante*). Ninguno de estos indicadores se inventó.

| Indicador | Dato que falta |
|---|---|
| Cumplimiento de meta de siniestralidad | Metas oficiales por periodo (y por sector o cliente) |
| Costo real vs presupuesto | Presupuesto mensual de costo de siniestralidad |
| Índice de frecuencia por horas (IF por 1.000.000 h) | Horas hombre trabajadas por cliente y mes |
| Causas del caso | Mecanismo, agente y parte del cuerpo |
| Efectividad de la prevención | Tipo de actividad, asistencia por trabajador y medición antes/después |
| Oportunidad de cierre de casos | Fecha de cierre de cada caso |
| Rentabilidad por cliente | Base de `valor_contrato` (mensual, anual o prima) y quién asume el costo |
| Seguimiento de visitas del coordinador | Registro de visitas o gestiones por cliente |
| Días de ausencia definitivos | Días cargados al cierre (los casos abiertos pueden sumar más días) |

Además se recomienda validar con el área dueña la regla leve/grave (529 casos no concuerdan con sus días) y los 77
costos atípicos antes de sacar conclusiones sobre costos.

## 8. Validación

- `python manage.py test`: 66 pruebas (15 del análisis) superadas.
- `python herramientas/validar_analisis.py`: 23/23 cifras coinciden con un recálculo independiente en pandas.
- `tests_e2e/prueba_navegador.py`: 59/59 verificaciones en navegador real, incluidos el drill-down de tres niveles,
  los permisos (403) y el alcance del coordinador en el análisis.
- Pipeline: `makemigrations --check` y `check --deploy` sin problemas.
