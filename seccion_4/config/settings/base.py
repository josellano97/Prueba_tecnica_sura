"""
Configuración común a todos los ambientes.

Los valores sensibles o que cambian por ambiente se leen de variables de entorno
(ver .env.example). dev.py y prod.py solo sobrescriben lo que difiere.
"""
from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# En local se leen las variables desde .env (en Azure se configuran como App Settings).
load_dotenv(BASE_DIR / ".env")


def env_bool(nombre: str, defecto: bool = False) -> bool:
    return os.environ.get(nombre, str(defecto)).strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def env_lista(nombre: str, defecto: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(nombre, defecto).split(",") if v.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_lista("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_lista("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.cuentas",
    "apps.tablero",
    "apps.analisis",
    "apps.agente",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.CabecerasSeguridadMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.navegacion",
            ],
        },
    },
]

# Base de datos: SQLite por defecto; en producción DATABASE_URL (p. ej. PostgreSQL en Azure).
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}",
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Autenticación -------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Asistente conversacional (agente de n8n) embebido en la app. Vacío = no se muestra.
AGENTE_CHAT_URL = os.environ.get("AGENTE_CHAT_URL", "")            # URL del chat del agente (…/webhook/<id>/chat)
AGENTE_CHAT_USUARIO = os.environ.get("AGENTE_CHAT_USUARIO", "")    # usuario y clave del Basic Auth del chat
AGENTE_CHAT_CLAVE = os.environ.get("AGENTE_CHAT_CLAVE", "")

LOGIN_URL = "cuentas:login"
LOGIN_REDIRECT_URL = "inicio"   # la raíz decide: análisis gerencial o tablero
LOGOUT_REDIRECT_URL = "cuentas:login"

# Sesiones: 8 horas de inactividad máxima, cookie inaccesible desde JavaScript.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(8 * 3600)))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- Internacionalización ------------------------------------------------------
LANGUAGE_CODE = "es-co"
LANGUAGES = [("es", "Español")]
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos (servidos por WhiteNoise, sin servidor adicional) --------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "apps.core.almacenamiento.EstaticosVersionados"},
}

# --- Seguridad común -----------------------------------------------------------
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# --- Registro (a consola: App Service lo recoge en Log Stream) --------------------
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"consola": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["consola"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["consola"], "level": LOG_LEVEL, "propagate": False},
        "seguridad": {"handlers": ["consola"], "level": "INFO", "propagate": False},
    },
}
