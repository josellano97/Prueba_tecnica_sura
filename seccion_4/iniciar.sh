#!/usr/bin/env bash
# Prepara y abre la aplicación en un solo paso (Linux / macOS).
#   La primera vez: entorno virtual, dependencias, base de datos SQLite y datos de demostración generados en el
#   código, con un usuario por rol (contraseñas mostradas una sola vez, o DEMO_PASSWORD si está definida).
#   Las siguientes veces: solo verifica dependencias y migraciones y abre el servidor. Nunca borra datos.
# Uso:
#   bash iniciar.sh            # solo en este equipo
#   bash iniciar.sh --red      # también desde otros equipos de la misma red (solo redes de confianza)
set -euo pipefail
cd "$(dirname "$0")"
PUERTO="${PUERTO:-8000}"
paso() { printf '\n==> %s\n' "$1"; }

# 1. Entorno virtual y dependencias
if [ ! -x .venv/bin/python ]; then
    paso "Creando el entorno virtual (.venv)"
    PY=""
    for c in python3 python; do
        if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then PY="$c"; break; fi
    done
    [ -n "$PY" ] || { echo "Se necesita Python 3.11 o superior (https://www.python.org/downloads/)."; exit 1; }
    "$PY" -m venv .venv
fi
paso "Instalando dependencias (requirements.txt)"
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

# 2. Base de datos y datos de demostración
PRIMERA_VEZ=0; [ -f db.sqlite3 ] || PRIMERA_VEZ=1
paso "Preparando la base de datos"
.venv/bin/python manage.py migrate --noinput -v 0
if [ "$PRIMERA_VEZ" = 1 ]; then
    paso "Generando los datos de demostración y un usuario por rol"
    .venv/bin/python manage.py cargar_datos_demo --usuarios-demo
    echo "   Guarde las contraseñas de arriba: no se vuelven a mostrar."
fi

# 3. Servidor
DIRECCION=127.0.0.1
if [ "${1:-}" = "--red" ]; then
    IPS="$(hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true)"
    export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,$(hostname),$(echo $IPS | tr ' ' ',')"
    DIRECCION=0.0.0.0
    for ip in $IPS; do echo "   http://$ip:$PUERTO/"; done
fi
paso "Abriendo la aplicación en http://127.0.0.1:$PUERTO/ (Ctrl+C para detenerla)"
exec .venv/bin/python manage.py runserver "$DIRECCION:$PUERTO"
