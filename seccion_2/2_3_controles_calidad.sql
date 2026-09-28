-- =====================================================================
-- Nombre      : controles_calidad_pipeline_diario
-- Se ejecuta  : después de construir staging.indicadores_cliente_diario (tabla
--               `resultado_pipeline`) y ANTES de publicarla en la capa que lee el tablero.
-- Regla       : si algún control con severidad 'bloqueante' falla, el orquestador NO
--               publica, conserva la versión de ayer en el tablero y envía una alerta.
--               Los controles 'advertencia' publican pero notifican.
-- Salida      : 1 fila por control: nombre, dimensión, valor observado, umbral, resultado.
-- =====================================================================
WITH params AS (
    SELECT CAST(CURRENT_DATE - INTERVAL 1 DAY AS DATE) AS fecha_corte   -- ayer: fecha de corte
),
-- ---------- Controles sobre las fuentes ----------
frescura AS (
    SELECT 'frescura_casos' AS control, 'Oportunidad' AS dimension, 'bloqueante' AS severidad,
           CAST(MAX(p.fecha_corte) - MAX(ca.fecha_ocurrencia) AS DOUBLE) AS valor,
           2.0 AS umbral, 'días desde el último caso registrado <= umbral' AS regla
    FROM casos ca CROSS JOIN params p
),
volumen AS (   -- casos del día de corte vs promedio diario de los 28 días previos
    SELECT 'volumen_casos_dia' AS control, 'Completitud' AS dimension, 'advertencia' AS severidad,
           ROUND(SUM(CASE WHEN ca.fecha_ocurrencia = p.fecha_corte THEN 1 ELSE 0 END) * 1.0
                 / NULLIF(SUM(CASE WHEN ca.fecha_ocurrencia BETWEEN p.fecha_corte - 28 AND p.fecha_corte - 1
                                   THEN 1 ELSE 0 END) / 28.0, 0), 2) AS valor,
           0.4 AS umbral, 'casos del día / promedio 28 d >= umbral (caída abrupta de carga)' AS regla
    FROM casos ca CROSS JOIN params p
    WHERE ca.estado <> 'anulado'
),
nulos AS (
    SELECT 'nulos_campos_clave_casos' AS control, 'Completitud' AS dimension, 'bloqueante' AS severidad,
           CAST(SUM(CASE WHEN id_cliente IS NULL OR fecha_ocurrencia IS NULL OR tipo IS NULL
                          OR estado IS NULL THEN 1 ELSE 0 END) AS DOUBLE) AS valor,
           0.0 AS umbral, 'registros con campos clave nulos = 0' AS regla
    FROM casos
),
duplicados AS (
    SELECT 'duplicados_id_caso' AS control, 'Unicidad' AS dimension, 'bloqueante' AS severidad,
           CAST(COUNT(*) - COUNT(DISTINCT id_caso) AS DOUBLE) AS valor,
           0.0 AS umbral, 'id_caso repetidos = 0' AS regla
    FROM casos
),
dominio AS (
    SELECT 'dominio_tipo_y_dias' AS control, 'Validez' AS dimension, 'bloqueante' AS severidad,
           CAST(SUM(CASE WHEN tipo NOT IN ('leve', 'grave') OR dias_ausencia < 0 OR costo < 0
                          OR fecha_ocurrencia > p.fecha_corte THEN 1 ELSE 0 END) AS DOUBLE) AS valor,
           0.0 AS umbral, 'tipo fuera de dominio, días/costo negativos o fechas futuras = 0' AS regla
    FROM casos CROSS JOIN params p
),
huerfanos AS (
    SELECT 'casos_sin_cliente' AS control, 'Consistencia' AS dimension, 'bloqueante' AS severidad,
           CAST(COUNT(*) AS DOUBLE) AS valor, 0.0 AS umbral,
           'casos cuyo id_cliente no existe en clientes = 0' AS regla
    FROM casos ca LEFT JOIN clientes c ON c.id_cliente = ca.id_cliente
    WHERE c.id_cliente IS NULL
),
cobertura_facturacion AS (
    SELECT 'cobertura_facturacion_mes' AS control, 'Completitud' AS dimension, 'advertencia' AS severidad,
           ROUND(AVG(CASE WHEN f.id_cliente IS NOT NULL THEN 1.0 ELSE 0.0 END), 3) AS valor,
           0.95 AS umbral, '% clientes activos con facturación del mes en curso >= umbral' AS regla
    FROM clientes c CROSS JOIN params p
    LEFT JOIN facturacion f ON f.id_cliente = c.id_cliente
                           AND f.periodo = CAST(DATE_TRUNC('month', p.fecha_corte) AS DATE)
    WHERE c.estado = 'activo'
),
-- ---------- Controles sobre el resultado del pipeline ----------
filas_resultado AS (
    SELECT 'filas_resultado_vs_activos' AS control, 'Completitud' AS dimension, 'bloqueante' AS severidad,
           CAST((SELECT COUNT(*) FROM resultado_pipeline)
                - (SELECT COUNT(*) FROM clientes WHERE estado = 'activo') AS DOUBLE) AS valor,
           0.0 AS umbral, 'filas del resultado - clientes activos = 0 (ni pérdidas ni duplicados)' AS regla
),
conciliacion AS (   -- el total del tablero debe cuadrar con la fuente
    SELECT 'conciliacion_casos_mes' AS control, 'Consistencia' AS dimension, 'bloqueante' AS severidad,
           CAST((SELECT SUM(casos_mes) FROM resultado_pipeline)
                - (SELECT COUNT(*) FROM casos ca JOIN clientes c USING (id_cliente) CROSS JOIN params p
                   WHERE c.estado = 'activo' AND ca.estado <> 'anulado'
                     AND ca.fecha_ocurrencia BETWEEN CAST(DATE_TRUNC('month', p.fecha_corte) AS DATE)
                                                 AND p.fecha_corte) AS DOUBLE) AS valor,
           0.0 AS umbral, 'suma casos_mes resultado - conteo directo en fuente = 0' AS regla
),
rango_tasa AS (
    SELECT 'tasa_fuera_de_rango' AS control, 'Validez' AS dimension, 'bloqueante' AS severidad,
           CAST(SUM(CASE WHEN tasa_incidencia < 0 OR tasa_incidencia > 100 THEN 1 ELSE 0 END) AS DOUBLE) AS valor,
           0.0 AS umbral, 'tasas negativas o > 100 por cada 100 trabajadores = 0' AS regla
    FROM resultado_pipeline
),
sin_dato AS (
    SELECT 'clientes_sin_tasa' AS control, 'Completitud' AS dimension, 'advertencia' AS severidad,
           ROUND(AVG(CASE WHEN clasificacion = 'sin dato' THEN 1.0 ELSE 0.0 END), 3) AS valor,
           0.05 AS umbral, '% de clientes sin tasa calculable <= umbral' AS regla
    FROM resultado_pipeline
),
todos AS (
    SELECT * FROM frescura UNION ALL SELECT * FROM volumen UNION ALL SELECT * FROM nulos
    UNION ALL SELECT * FROM duplicados UNION ALL SELECT * FROM dominio UNION ALL SELECT * FROM huerfanos
    UNION ALL SELECT * FROM cobertura_facturacion UNION ALL SELECT * FROM filas_resultado
    UNION ALL SELECT * FROM conciliacion UNION ALL SELECT * FROM rango_tasa UNION ALL SELECT * FROM sin_dato
)
SELECT control, dimension, severidad, valor, umbral, regla,
       CASE
         WHEN control IN ('volumen_casos_dia', 'cobertura_facturacion_mes')
              THEN CASE WHEN valor >= umbral THEN 'OK' ELSE 'FALLA' END
         WHEN control = 'filas_resultado_vs_activos' OR control = 'conciliacion_casos_mes'
              THEN CASE WHEN valor = umbral THEN 'OK' ELSE 'FALLA' END
         ELSE CASE WHEN valor <= umbral THEN 'OK' ELSE 'FALLA' END
       END AS resultado
FROM todos
ORDER BY severidad, control;
