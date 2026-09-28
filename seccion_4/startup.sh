#!/usr/bin/env bash
# Comando de arranque en Azure App Service (Linux). Se configura como "Startup Command": bash startup.sh
# 1) aplica migraciones pendientes (incluye la creación inicial de roles)  2) arranca gunicorn.
set -euo pipefail

python manage.py migrate --noinput

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
