-- =====================================================================
-- Nombre      : top15_clientes_atencion_prioritaria
-- Uso         : Ejecución semanal (lunes) para planear visitas de la semana.
-- Dialecto    : ANSI / DuckDB / Spark SQL
-- Grano       : 15 filas, 1 por cliente, ordenadas por puntaje de prioridad.
--
-- Criterio: un cliente necesita atención prioritaria cuando se accidenta MÁS de lo
-- esperado, con incidentes MÁS serios, está EMPEORANDO, le cuesta más por trabajador,
-- tiene casos graves aún ABIERTOS y lleva tiempo SIN prevención. Cada criterio se
-- convierte en un percentil (0 a 1) entre los clientes activos para que sean
-- comparables sin importar su unidad, y se ponderan así:
--
--   Componente                                   Peso  Ventana
--   1. Frecuencia: tasa de casos ajustada         30 %  últimos 90 días
--   2. Severidad: días perdidos por trabajador    20 %  últimos 90 días
--   3. Tendencia: casos 90 d vs 90 d anteriores   15 %  180 días
--   4. Costo por trabajador                       10 %  últimos 12 meses
--   5. Casos graves abiertos                      10 %  a la fecha de corte
--   6. Brecha de prevención (días sin actividad)  10 %  a la fecha de corte
--   7. Clase de riesgo (1-5)                        5 %  estructural
--
-- Ajuste por tamaño (componente 1): la tasa se "suaviza" hacia el promedio de su
-- clase de riesgo con una exposición de referencia de 300 trabajadores-mes. Así un
-- cliente de 15 trabajadores con 1 caso no sube al primer lugar solo por azar,
-- mientras que un cliente grande con tasa alta sí lo hace.
-- =====================================================================
WITH params AS (
    SELECT CAST(CURRENT_DATE - INTERVAL 1 DAY AS DATE) AS fecha_corte,   -- ayer: fecha de corte
           300.0                                        AS exposicion_ref  -- trabajadores-mes
),
activos AS (
    SELECT id_cliente, nombre, sector, clase_riesgo
    FROM clientes WHERE estado = 'activo'
),
casos_validos AS (
    SELECT ca.*
    FROM casos ca CROSS JOIN params p
    WHERE ca.estado <> 'anulado'
      AND ca.fecha_ocurrencia <= p.fecha_corte
      AND ca.fecha_ocurrencia >  CAST(p.fecha_corte - INTERVAL 12 MONTH AS DATE)
),
casos_agg AS (
    SELECT cv.id_cliente,
           SUM(CASE WHEN cv.fecha_ocurrencia > p.fecha_corte - 90 THEN 1 ELSE 0 END)            AS casos_90d,
           SUM(CASE WHEN cv.fecha_ocurrencia <= p.fecha_corte - 90
                     AND cv.fecha_ocurrencia >  p.fecha_corte - 180 THEN 1 ELSE 0 END)          AS casos_prev_90d,
           SUM(CASE WHEN cv.fecha_ocurrencia > p.fecha_corte - 90 THEN cv.dias_ausencia ELSE 0 END) AS dias_90d,
           SUM(CASE WHEN cv.fecha_ocurrencia > p.fecha_corte - 90 AND cv.tipo = 'grave' THEN 1 ELSE 0 END) AS graves_90d,
           SUM(CASE WHEN cv.tipo = 'grave' AND cv.estado = 'abierto' THEN 1 ELSE 0 END)          AS graves_abiertos,
           SUM(COALESCE(cv.costo, 0))                                                             AS costo_12m
    FROM casos_validos cv CROSS JOIN params p
    GROUP BY cv.id_cliente
),
trab AS (   -- trabajadores promedio: últimos 3 periodos (90 d) y últimos 12 periodos (costo)
    SELECT f.id_cliente,
           AVG(CASE WHEN f.periodo >= CAST(DATE_TRUNC('month', p.fecha_corte) - INTERVAL 2 MONTH AS DATE)
                    THEN f.trabajadores_activos END)  AS trab_3m,
           AVG(f.trabajadores_activos)                AS trab_12m
    FROM facturacion f CROSS JOIN params p
    WHERE f.periodo >= CAST(DATE_TRUNC('month', p.fecha_corte) - INTERVAL 11 MONTH AS DATE)
      AND f.periodo <= p.fecha_corte
    GROUP BY f.id_cliente
),
prev AS (
    SELECT pr.id_cliente, MAX(pr.fecha) AS ultima_prevencion
    FROM prevencion pr CROSS JOIN params p
    WHERE pr.fecha <= p.fecha_corte
    GROUP BY pr.id_cliente
),
base AS (
    SELECT a.*,
           COALESCE(ca.casos_90d, 0)        AS casos_90d,
           COALESCE(ca.casos_prev_90d, 0)   AS casos_prev_90d,
           COALESCE(ca.dias_90d, 0)         AS dias_90d,
           COALESCE(ca.graves_90d, 0)       AS graves_90d,
           COALESCE(ca.graves_abiertos, 0)  AS graves_abiertos,
           COALESCE(ca.costo_12m, 0)        AS costo_12m,
           t.trab_3m, t.trab_12m,
           t.trab_3m * 3                    AS exposicion_3m,          -- trabajadores-mes
           pv.ultima_prevencion,
           -- sin prevención registrada => se trata como 365 días (máxima brecha)
           COALESCE(CAST(p.fecha_corte - pv.ultima_prevencion AS INTEGER), 365) AS dias_sin_prevencion
    FROM activos a
    CROSS JOIN params p
    JOIN trab t          ON t.id_cliente  = a.id_cliente     -- exige facturación reciente
    LEFT JOIN casos_agg ca ON ca.id_cliente = a.id_cliente
    LEFT JOIN prev pv    ON pv.id_cliente = a.id_cliente
    WHERE t.trab_3m > 0
),
tasa_clase AS (   -- tasa mensual por cada 100 trabajadores, promedio de la clase
    SELECT clase_riesgo, SUM(casos_90d) * 100.0 / SUM(exposicion_3m) AS tasa_clase
    FROM base GROUP BY clase_riesgo
),
metricas AS (
    SELECT b.*, tc.tasa_clase,
           b.casos_90d * 100.0 / b.exposicion_3m                                   AS tasa_90d,
           (b.casos_90d + p.exposicion_ref * tc.tasa_clase / 100.0) * 100.0
               / (b.exposicion_3m + p.exposicion_ref)                              AS tasa_ajustada,
           b.dias_90d * 1.0 / b.trab_3m                                             AS dias_perdidos_x_trab,
           (b.casos_90d + 1.0) / (b.casos_prev_90d + 1.0)                           AS indice_tendencia,
           b.costo_12m / b.trab_12m                                                 AS costo_x_trab_12m
    FROM base b JOIN tasa_clase tc USING (clase_riesgo) CROSS JOIN params p
),
percentiles AS (
    SELECT m.*,
           PERCENT_RANK() OVER (ORDER BY tasa_ajustada)        AS p_frecuencia,
           PERCENT_RANK() OVER (ORDER BY dias_perdidos_x_trab) AS p_severidad,
           PERCENT_RANK() OVER (ORDER BY indice_tendencia)     AS p_tendencia,
           PERCENT_RANK() OVER (ORDER BY costo_x_trab_12m)     AS p_costo,
           PERCENT_RANK() OVER (ORDER BY graves_abiertos)      AS p_abiertos,
           PERCENT_RANK() OVER (ORDER BY dias_sin_prevencion)  AS p_prevencion,
           (clase_riesgo - 1) / 4.0                            AS p_clase
    FROM metricas m
),
puntaje AS (
    SELECT p.*,
           0.30 * p_frecuencia AS c_frecuencia, 0.20 * p_severidad  AS c_severidad,
           0.15 * p_tendencia  AS c_tendencia,  0.10 * p_costo      AS c_costo,
           0.10 * p_abiertos   AS c_abiertos,   0.10 * p_prevencion AS c_prevencion,
           0.05 * p_clase      AS c_clase
    FROM percentiles p
),
final AS (
    SELECT pu.*,
           ROUND(100 * (c_frecuencia + c_severidad + c_tendencia + c_costo
                        + c_abiertos + c_prevencion + c_clase), 1) AS puntaje_prioridad
    FROM puntaje pu
)
SELECT ROW_NUMBER() OVER (ORDER BY puntaje_prioridad DESC, tasa_ajustada DESC, id_cliente) AS prioridad,
       id_cliente, nombre, sector, clase_riesgo,
       puntaje_prioridad,
       ROUND(tasa_90d, 2)              AS tasa_mensual_90d,
       ROUND(tasa_ajustada, 2)         AS tasa_ajustada,
       casos_90d, casos_prev_90d, graves_90d, graves_abiertos,
       ROUND(dias_perdidos_x_trab, 2)  AS dias_perdidos_x_trab,
       ROUND(costo_x_trab_12m, 0)      AS costo_x_trab_12m,
       dias_sin_prevencion,
       -- Motivo principal: el criterio en el que el cliente está más alto frente a los
       -- demás (mayor percentil). Le dice al coordinador QUÉ revisar en la visita.
       CASE GREATEST(p_frecuencia, p_severidad, p_tendencia, p_costo, p_abiertos, p_prevencion)
            WHEN p_frecuencia THEN 'Alta frecuencia de casos'
            WHEN p_severidad  THEN 'Casos severos (días perdidos)'
            WHEN p_tendencia  THEN 'Casos en aumento'
            WHEN p_costo      THEN 'Alto costo por trabajador'
            WHEN p_abiertos   THEN 'Casos graves abiertos'
            ELSE 'Sin prevención reciente' END AS motivo_principal
FROM final
ORDER BY prioridad
LIMIT 15;
