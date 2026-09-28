"""
Producción (Azure App Service). Todo valor sensible llega por variables de entorno;
si falta algo imprescindible la aplicación no arranca (falla temprano y explícita).
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env_bool, env_lista

DEBUG = False

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY no está definida o es demasiado corta (mínimo 50 caracteres).")

ALLOWED_HOSTS = env_lista("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS es obligatoria en producción (p. ej. miapp.azurewebsites.net).")
# Azure App Service consulta el sitio internamente con la IP del contenedor (sondeos de salud).
if env_bool("AZURE_APP_SERVICE", True):
    ALLOWED_HOSTS += [".azurewebsites.net", "169.254.129.1", "169.254.129.2", "169.254.129.3", "169.254.129.4"]
CSRF_TRUSTED_ORIGINS = env_lista("DJANGO_CSRF_TRUSTED_ORIGINS") or [f"https://{h}" for h in ALLOWED_HOSTS if "." in h and not h[0].isdigit() and not h.startswith(".")]

# HTTPS: App Service termina TLS y reenvía la cabecera X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
# Decisión: no se inscribe en la lista de precarga HSTS (es casi irreversible y el dominio inicial
# *.azurewebsites.net no es propio). Se puede activar al usar un dominio corporativo definitivo.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"

# Errores: nunca se muestran trazas al usuario; se registran en consola (Log Stream / App Insights).
ADMINS = [("Soporte", e) for e in env_lista("DJANGO_ADMINS_EMAILS")]
