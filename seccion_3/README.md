# Sección 3 · Validación de calidad del archivo de facturación

Script que revisa cada carga nueva del archivo de facturación antes de que entre al pipeline: califica su calidad,
separa los registros válidos de los rechazados y bloquea la carga si no cumple el umbral.

## Cómo ejecutar

```bash
python seccion_3/validar_calidad_facturacion.py      # genera un archivo de prueba y lo valida
python -m pytest seccion_3 -q                        # pruebas unitarias
```

Para validar un archivo propio: `--entrada archivo.csv` (o `.xlsx`). Los resultados quedan en `salida/`: el reporte de
calidad (JSON), los registros válidos (Parquet) y los rechazados con su motivo (Excel).

El archivo de prueba trae errores a propósito, así que lo esperado es que la carga salga **RECHAZADA**.
