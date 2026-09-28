"""Pruebas automáticas: base de datos en memoria y hash de contraseñas rápido."""
from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "clave-exclusiva-para-pruebas-automaticas-no-es-un-secreto-real-000000"
ALLOWED_HOSTS = ["testserver", "localhost"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
LOGGING = {"version": 1, "disable_existing_loggers": True,
           "handlers": {"nulo": {"class": "logging.NullHandler"}},
           "root": {"handlers": ["nulo"]},
           "loggers": {"seguridad": {"handlers": ["nulo"], "propagate": False},
                       "django": {"handlers": ["nulo"], "propagate": False}}}
