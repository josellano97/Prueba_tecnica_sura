# Archivo WSGI de PythonAnywhere para la aplicacion de monitoreo (Django).
import os
import sys

RUTA = '/home/josealejandrollanocortes/monitoreo'
if RUTA not in sys.path:
    sys.path.insert(0, RUTA)
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.prod'   # las demas variables se leen de monitoreo/.env

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()