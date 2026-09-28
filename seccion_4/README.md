# Sección 4 · Tablero de monitoreo (aplicación web)

Aplicación web para monitorear la siniestralidad de los clientes: análisis gerencial, tablero con filtros, calidad de
datos y la pestaña **Agente Sura** (chat con un agente de IA hecho en n8n). Cada coordinador ve solo sus clientes.

Hecha en **Django (Python)**: permite usuarios con contraseña, permisos por rol y cálculos en el servidor, sin
licencias.

## Cómo usarla

Abra <https://josealejandrollanocortes.pythonanywhere.com> desde el computador o el celular. La contraseña de los
usuarios de prueba se entrega aparte.

Para ejecutarla en su computador (Windows): doble clic en `iniciar.bat`. En Linux o Mac, ejecute `./iniciar.sh`. La
primera vez instala lo necesario y genera los datos.

## Conexión a un Lakehouse en producción

Una carga diaria leería la capa gold del Lakehouse (SQL analytics endpoint, con identidad administrada) y guardaría el
resumen por cliente y mes en la base de la aplicación. El comando `cargar_datos_proyecto` ya hace esa carga con
controles de calidad; solo cambiaría la fuente.
