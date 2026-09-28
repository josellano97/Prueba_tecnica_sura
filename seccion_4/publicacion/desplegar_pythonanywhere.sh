#!/bin/bash
# Instala o actualiza la aplicacion en PythonAnywhere. Deja el resultado en ~/desplegar.log
set -e
cd "$HOME"
PY=""
for v in 3.11 3.12 3.13 3.10; do if command -v "python$v" >/dev/null; then PY="python$v"; break; fi; done
echo "PYVER=${PY#python}"
rm -rf monitoreo_nuevo
"$PY" -c "import zipfile; zipfile.ZipFile('monitoreo.zip').extractall('monitoreo_nuevo')"
rm -rf monitoreo_anterior
if [ -d monitoreo ]; then mv monitoreo monitoreo_anterior; fi
mv monitoreo_nuevo/monitoreo monitoreo
rmdir monitoreo_nuevo
cp configuracion_app.env monitoreo/.env
chmod 600 monitoreo/.env configuracion_app.env
if [ ! -x .virtualenvs/monitoreo/bin/python ]; then "$PY" -m venv .virtualenvs/monitoreo; fi
.virtualenvs/monitoreo/bin/pip install -q --disable-pip-version-check -r monitoreo/requirements-pythonanywhere.txt
cd monitoreo
export DJANGO_SETTINGS_MODULE=config.settings.prod
../.virtualenvs/monitoreo/bin/python manage.py migrate --noinput
../.virtualenvs/monitoreo/bin/python manage.py check --deploy
echo DESPLIEGUE_OK