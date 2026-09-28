"""Punto de entrada WSGI (gunicorn en Azure App Service). Por defecto usa la configuración de producción."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
application = get_wsgi_application()
