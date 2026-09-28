-- =====================================================================
-- Biblioteca compartida de consultas
-- Nombre      : siniestralidad_12m_por_cliente_activo
-- Versión     : 2.0 (corrige v1.0 heredada)            Dialecto: ANSI / DuckDB / Spark SQL
-- Propósito   : Resumir, por cliente activo, los incidentes de los últimos 12 meses
--               (cantidad, graves, costo) y el costo por trabajador, con un ranking de
--               costo dentro de cada clase de riesgo.
-- Grano       : 1 fila por cliente activo con al menos 1 caso válido en la ventana.
-- Tablas      : clientes, casos, facturacion
-- Parámetros  : fecha_corte (por defecto: día anterior a la ejecución)
-- Cambios vs v1.0 (ver documento, pregunta 2.1):
--   1. Se pre-agrega cada tabla hecho en su propio CTE antes de unir -> elimina la
--      multiplicación de filas (fan-out) que inflaba casos y costos ~6 veces.
--   2. 'Grave' se toma del campo oficial casos.tipo, no de dias_ausencia > 15.
--   3. Se excluyen casos anulados.
--   4. Ventanas explícitas y cerradas contra una fecha de corte (reproducible),
--      y la misma ventana de 12 meses para costo y trabajadores.
-- =====================================================================
WITH params AS (
    SELECT CAST(CURRENT_DATE - INTERVAL 1 DAY AS DATE) AS fecha_corte   -- ayer: fecha de corte
),
ventana AS (
    SELECT fecha_corte,
           CAST(fecha_corte - INTERVAL 12 MONTH AS DATE)                           AS desde_casos,
           CAST(DATE_TRUNC('month', fecha_corte) - INTERVAL 11 MONTH AS DATE)       AS desde_periodo
    FROM params
),
casos_12m AS (                       -- 1 fila por cliente
    SELECT ca.id_cliente,
           COUNT(*)                                             AS total_casos,
           SUM(CASE WHEN ca.tipo = 'grave' THEN 1 ELSE 0 END)   AS casos_graves,
           SUM(COALESCE(ca.costo, 0))                           AS costo_total,
           SUM(CASE WHEN ca.costo IS NULL THEN 1 ELSE 0 END)    AS casos_sin_costo
    FROM casos ca CROSS JOIN ventana v
    WHERE ca.fecha_ocurrencia >  v.desde_casos
      AND ca.fecha_ocurrencia <= v.fecha_corte
      AND ca.estado <> 'anulado'
    GROUP BY ca.id_cliente
),
trabajadores_12m AS (                -- 1 fila por cliente
    SELECT f.id_cliente,
           AVG(f.trabajadores_activos)                          AS trabajadores_prom,
           COUNT(*)                                             AS periodos_facturados
    FROM facturacion f CROSS JOIN ventana v
    WHERE f.periodo >= v.desde_periodo
      AND f.periodo <= v.fecha_corte
    GROUP BY f.id_cliente
),
base AS (
    SELECT c.id_cliente, c.nombre, c.sector, c.clase_riesgo,
           ca.total_casos, ca.casos_graves, ca.costo_total, ca.casos_sin_costo,
           t.trabajadores_prom, t.periodos_facturados
    FROM clientes c
    JOIN casos_12m ca             ON ca.id_cliente = c.id_cliente
    LEFT JOIN trabajadores_12m t  ON t.id_cliente  = c.id_cliente
    WHERE c.estado = 'activo'
)
SELECT id_cliente, nombre, sector, clase_riesgo,
       total_casos, casos_graves, costo_total,
       ROUND(trabajadores_prom, 1)                                      AS trabajadores_prom,
       ROUND(casos_graves * 100.0 / NULLIF(total_casos, 0), 1)          AS pct_graves,
       ROUND(costo_total / NULLIF(trabajadores_prom, 0), 0)             AS costo_x_trab,
       DENSE_RANK() OVER (PARTITION BY clase_riesgo
                          ORDER BY costo_total DESC)                    AS ranking_clase,
       periodos_facturados,                -- < 12 => costo_x_trab menos confiable
       casos_sin_costo                     -- > 0  => costo_total subestimado
FROM base
ORDER BY costo_total DESC, id_cliente;
