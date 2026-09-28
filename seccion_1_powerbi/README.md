# Sección 1 · Tablero Power BI "Siniestralidad y prevención"

Tablero que aplica las respuestas de la sección 1: el modelo semántico compartido, el storytelling, la seguridad por
coordinador (RLS) y las medidas A, B y C.

## Cómo ejecutar

Requiere **Power BI Desktop** (gratis, solo para Windows).

- **Forma rápida:** abra `Siniestralidad_Clientes.pbix`. Ya trae los datos, no necesita Python.
- **Desde el código:**

  ```bash
  python datos/generar_datos.py
  python seccion_1_powerbi/construir_pbip.py
  ```

  Luego abra `Siniestralidad_Clientes.pbip` y pulse **Inicio › Actualizar**.
