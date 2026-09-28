"""
Tokens de acceso para el agente conversacional (n8n).

Cada token pertenece a un usuario de la aplicación: el agente ve exactamente lo que ese usuario puede ver
(todos los clientes, o solo los de un coordinador). Solo se guarda la huella SHA-256 del token; el token en
claro se muestra una única vez al crearlo.
"""
import hashlib
import secrets

from django.conf import settings
from django.db import models


def huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenAgente(models.Model):
    nombre = models.CharField(max_length=80, help_text="Para qué se usa, p. ej. «n8n - chat de prueba»")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tokens_agente",
                                help_text="El agente verá solo lo que este usuario puede ver")
    huella = models.CharField(max_length=64, unique=True, editable=False)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "token del agente"
        verbose_name_plural = "tokens del agente"
        ordering = ["-creado"]

    def __str__(self):
        return f"{self.nombre} ({self.usuario})"

    @classmethod
    def crear(cls, nombre: str, usuario) -> tuple["TokenAgente", str]:
        """Crea un token y devuelve (registro, token en claro). El token en claro no se vuelve a poder ver."""
        token = "agt_" + secrets.token_urlsafe(32)
        return cls.objects.create(nombre=nombre, usuario=usuario, huella=huella(token)), token
