-- =====================================================================
-- Nombre      : pipeline_diario_tablero_ejecutivo  (capa gold: gold.indicadores_cliente_diario)
-- Frecuencia  : diaria, 05:00, a corte del día anterior.
-- Dialecto    : ANSI / DuckDB / Spark SQL
-- Grano       : 1 fila por cliente activo y fecha de corte.
-- Reglas de negocio:
--   * Caso válido = estado <> 'anulado'.
--   * Mes en curso = del día 1 del mes de la fecha de corte hasta la fecha de corte.
--   * Mes anterior = mes calendario anterior completo (lo que pide el requerimiento).
--     Se agrega además el mes anterior "al mismo corte" (mismos días transcurridos),
--     que es la comparación justa mientras el mes en curso está incompleto.
--   * Tasa de incidencia = casos del mes / trabajadores activos del mes * 100.
--     Trabajadores activos = facturacion.trabajadores_activos del periodo del mes en
--     curso; si aún no se ha facturado, se usa el último periodo disponible y se marca.
--   * Prevención 30 días = actividades con fecha en (corte - 30, corte].
--   * Clasificación: 'crítico' tasa > 5 | 'moderado' 2 <= tasa <= 5 | 'bajo' tasa < 2
--     | 'sin dato' si no hay trabajadores activos (no se puede calcular la tasa).
-- =====================================================================
WITH params AS (
    SELECT CAST(CURRENT_DATE - INTERVAL 1 DAY AS DATE) AS fecha_corte   -- ayer: fecha de corte
),
fechas AS (
    SELECT fecha_corte,
           CAST(DATE_TRUNC('month', fecha_corte) AS DATE)                              AS ini_mes,
           CAST(DATE_TRUNC('month', fecha_corte) - INTERVAL 1 MONTH AS DATE)           AS ini_mes_ant,
           CAST(DATE_TRUNC('month', fecha_corte) - INTERVAL 1 DAY AS DATE)             AS fin_mes_ant,
           -- mismo día del mes anterior (acotado al último día si el mes anterior es más corto)
           LEAST(CAST(fecha_corte - INTERVAL 1 MONTH AS DATE),
                 CAST(DATE_TRUNC('month', fecha_corte) - INTERVAL 1 DAY AS DATE))      AS corte_mes_ant,
           EXTRACT(DAY FROM fecha_corte)                                               AS dias_transcurridos,
           EXTRACT(DAY FROM CAST(DATE_TRUNC('month', fecha_corte) + INTERVAL 1 MONTH
                                 - INTERVAL 1 DAY AS DATE))                            AS dias_mes
    FROM params
),
clientes_activos AS (
    SELECT id_cliente, nombre, sector, clase_riesgo
    FROM clientes WHERE estado = 'activo'
),
casos_mes AS (
    SELECT ca.id_cliente,
           SUM(CASE WHEN ca.fecha_ocurrencia BETWEEN f.ini_mes     AND f.fecha_corte   THEN 1 ELSE 0 END) AS casos_mes,
           SUM(CASE WHEN ca.fecha_ocurrencia BETWEEN f.ini_mes_ant AND f.fin_mes_ant   THEN 1 ELSE 0 END) AS casos_mes_anterior,
           SUM(CASE WHEN ca.fecha_ocurrencia BETWEEN f.ini_mes_ant AND f.corte_mes_ant THEN 1 ELSE 0 END) AS casos_mes_ant_mismo_corte,
           SUM(CASE WHEN ca.fecha_ocurrencia BETWEEN f.ini_mes AND f.fecha_corte
                     AND ca.tipo = 'grave' THEN 1 ELSE 0 END)                                         AS casos_graves_mes
    FROM casos ca CROSS JOIN fechas f
    WHERE ca.estado <> 'anulado'
      AND ca.fecha_ocurrencia BETWEEN f.ini_mes_ant AND f.fecha_corte
    GROUP BY ca.id_cliente
),
facturacion_rank AS (   -- periodo del mes en curso o, si falta, el último anterior
    SELECT fa.id_cliente, fa.periodo, fa.trabajadores_activos,
           ROW_NUMBER() OVER (PARTITION BY fa.id_cliente ORDER BY fa.periodo DESC) AS rn
    FROM facturacion fa CROSS JOIN fechas f
    WHERE fa.periodo <= f.ini_mes
),
trabajadores AS (
    SELECT id_cliente, periodo AS periodo_trabajadores, trabajadores_activos
    FROM facturacion_rank WHERE rn = 1
),
prevencion_30d AS (
    SELECT pr.id_cliente, COUNT(*) AS actividades_prevencion_30d,
           SUM(pr.participantes)   AS participantes_prevencion_30d
    FROM prevencion pr CROSS JOIN fechas f
    WHERE pr.fecha >  CAST(f.fecha_corte - INTERVAL 30 DAY AS DATE)
      AND pr.fecha <= f.fecha_corte
    GROUP BY pr.id_cliente
),
calculo AS (
    SELECT f.fecha_corte, c.id_cliente, c.nombre, c.sector, c.clase_riesgo,
           COALESCE(cm.casos_mes, 0)                    AS casos_mes,
           COALESCE(cm.casos_mes_anterior, 0)           AS casos_mes_anterior,
           COALESCE(cm.casos_mes_ant_mismo_corte, 0)    AS casos_mes_ant_mismo_corte,
           COALESCE(cm.casos_graves_mes, 0)             AS casos_graves_mes,
           t.trabajadores_activos,
           t.periodo_trabajadores,
           (t.periodo_trabajadores < f.ini_mes)         AS trabajadores_de_periodo_anterior,
           COALESCE(p.actividades_prevencion_30d, 0)    AS actividades_prevencion_30d,
           COALESCE(p.participantes_prevencion_30d, 0)  AS participantes_prevencion_30d,
           f.dias_transcurridos, f.dias_mes
    FROM clientes_activos c
    CROSS JOIN fechas f
    LEFT JOIN casos_mes cm     ON cm.id_cliente = c.id_cliente
    LEFT JOIN trabajadores t   ON t.id_cliente  = c.id_cliente
    LEFT JOIN prevencion_30d p ON p.id_cliente  = c.id_cliente
),
indicadores AS (
    SELECT *,
           casos_mes - casos_mes_anterior                                           AS var_casos_vs_mes_ant,
           ROUND((casos_mes - casos_mes_anterior) * 100.0
                 / NULLIF(casos_mes_anterior, 0), 1)                                AS var_pct_vs_mes_ant,
           casos_mes - casos_mes_ant_mismo_corte                                    AS var_casos_vs_mismo_corte,
           casos_mes * 100.0 / NULLIF(trabajadores_activos, 0)                      AS tasa_incidencia
    FROM calculo
)
SELECT fecha_corte, id_cliente, nombre, sector, clase_riesgo,
       casos_mes, casos_mes_anterior, var_casos_vs_mes_ant, var_pct_vs_mes_ant,
       casos_mes_ant_mismo_corte, var_casos_vs_mismo_corte,
       casos_graves_mes,
       trabajadores_activos, periodo_trabajadores, trabajadores_de_periodo_anterior,
       ROUND(tasa_incidencia, 2)                                                    AS tasa_incidencia,
       -- Informativa: tasa proyectada a mes completo (no se usa para clasificar)
       ROUND(tasa_incidencia * dias_mes / dias_transcurridos, 2)                    AS tasa_proyectada_mes,
       actividades_prevencion_30d, participantes_prevencion_30d,
       CASE WHEN tasa_incidencia IS NULL THEN 'sin dato'
            WHEN tasa_incidencia > 5     THEN 'crítico'
            WHEN tasa_incidencia >= 2    THEN 'moderado'
            ELSE 'bajo' END                                                         AS clasificacion,
       CURRENT_TIMESTAMP                                                            AS fecha_proceso
FROM indicadores
ORDER BY tasa_incidencia DESC NULLS LAST, id_cliente;
