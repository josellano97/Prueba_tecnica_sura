"""Perfil automático para cada usuario y registro de eventos de autenticación (sin datos sensibles)."""
import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Perfil

log = logging.getLogger("seguridad")


def _ip(request):
    if request is None:
        return "-"
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return reenviada.split(",")[0].strip() if reenviada else request.META.get("REMOTE_ADDR", "-")


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def crear_perfil(sender, instance, created, **kwargs):
    if created:
        Perfil.objects.get_or_create(usuario=instance)


@receiver(user_logged_in)
def registrar_ingreso(sender, request, user, **kwargs):
    log.info("Ingreso exitoso: usuario=%s ip=%s", user.get_username(), _ip(request))


@receiver(user_logged_out)
def registrar_salida(sender, request, user, **kwargs):
    log.info("Cierre de sesión: usuario=%s ip=%s", user.get_username() if user else "-", _ip(request))


@receiver(user_login_failed)
def registrar_fallo(sender, credentials, request=None, **kwargs):
    # Nunca se registra la contraseña: solo el usuario intentado y la IP.
    log.warning("Ingreso fallido: usuario=%s ip=%s", credentials.get("username", "-"), _ip(request))
