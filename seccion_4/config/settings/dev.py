"""Desarrollo local: DEBUG activo y clave de desarrollo si no se define una."""
from .base import *  # noqa: F401,F403
from .base import env_lista
import os

DEBUG = True
# Clave solo para desarrollo local; en producción prod.py exige DJANGO_SECRET_KEY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "solo-desarrollo-no-usar-en-produccion"
ALLOWED_HOSTS = env_lista("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
