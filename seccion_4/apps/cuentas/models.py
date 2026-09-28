from django.conf import settings
from django.db import models


class Perfil(models.Model):
    """Datos del usuario que Django no trae: su coordinador asociado (define qué clientes ve)."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    coordinador = models.ForeignKey("tablero.Coordinador", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="usuarios",
                                    help_text="Si el usuario no puede ver todos los clientes, solo verá los de este coordinador.")
    cargo = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "perfil de usuario"
        verbose_name_plural = "perfiles de usuario"

    def __str__(self):
        return f"Perfil de {self.usuario.get_username()}"
