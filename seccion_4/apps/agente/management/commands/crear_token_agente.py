"""
Crea un token para el agente conversacional. El token se muestra UNA sola vez.

    python manage.py crear_token_agente --usuario consulta_demo --nombre "n8n - chat"
    python manage.py crear_token_agente --usuario coordinador_demo --nombre "n8n - coordinador 01"

El agente verá exactamente lo que el usuario elegido puede ver (con un coordinador, solo su cartera).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.agente.models import TokenAgente


class Command(BaseCommand):
    help = "Crea un token de solo lectura para el agente conversacional (se muestra una sola vez)."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", required=True, help="Usuario de la app cuyo alcance tendrá el agente")
        parser.add_argument("--nombre", default="Agente n8n", help="Para qué se usa el token")

    def handle(self, *args, **o):
        try:
            usuario = get_user_model().objects.get(username=o["usuario"])
        except get_user_model().DoesNotExist as e:
            raise CommandError(f"No existe el usuario «{o['usuario']}».") from e
        if not usuario.has_perm("tablero.ver_tablero"):
            raise CommandError("Ese usuario no tiene permiso para ver el tablero; el agente no vería nada.")
        _, token = TokenAgente.crear(o["nombre"], usuario)
        self.stdout.write(f"Token creado para {usuario.username} (guárdelo: no se vuelve a mostrar):")
        self.stdout.write(token)
