# Prueba técnica · Analista de Datos y Analítica

Solución de la prueba técnica. Todos los datos son sintéticos y se generan con Python.

| Sección | Qué hay | Carpeta |
|---|---|---|
| Respuestas escritas (1, 2, 5 y 6) | Documento en PDF y Word | [documento/](documento/) |
| 1 · Power BI | Tablero en Power BI Desktop | [seccion_1_powerbi/](seccion_1_powerbi/) |
| 2 · SQL | Consultas SQL y su validación | [seccion_2/](seccion_2/) |
| 3 · Python | Validador de calidad del archivo de facturación | [seccion_3/](seccion_3/) |
| 4 · Aplicación web | Tablero web con agente conversacional (n8n): <https://josealejandrollanocortes.pythonanywhere.com> | [seccion_4/](seccion_4/) |

## Cómo ejecutar

Requiere Python 3.11 o superior.

```bash
python -m venv .venv
.venv\Scripts\activate            # en Linux o Mac: source .venv/bin/activate
pip install -r requirements.txt
python datos/generar_datos.py     # genera los datos de prueba (con fecha de corte de ayer)
```

Después, siga el README de cada sección.
