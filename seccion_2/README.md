# Sección 2 · SQL

Consultas de la sección 2: la consulta heredada y su corrección (2.1), el top 15 de clientes para visitas (2.2) y el
pipeline diario con sus controles de calidad (2.3). Ninguna tiene fechas fijas: el corte siempre es el día anterior.

## Cómo ejecutar

```bash
python datos/generar_datos.py
python seccion_2/validar_sql.py
```

El validador ejecuta todas las consultas y compara sus resultados con un cálculo independiente en Python. Los
resultados quedan en `resultados/`.
