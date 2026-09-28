"""
API de solo lectura para el agente conversacional (n8n).

Autenticación: cabecera `Authorization: Bearer <token>` (token creado con `manage.py crear_token_agente`).
El token pertenece a un usuario de la app y el agente ve solo lo que ese usuario puede ver.
Todas las respuestas son JSON; los errores también, con un mensaje que el agente puede repetir al usuario.
"""
import hmac
from datetime import timedelta
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.generic import TemplateView

from apps.core.context_processors import _asistente

from . import servicios as S
from .models import TokenAgente, huella


def _json(datos, estado=200):
    return JsonResponse(datos, status=estado, json_dumps_params={"ensure_ascii": False})


def con_token(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        cabecera = request.headers.get("Authorization", "")
        token = cabecera[7:].strip() if cabecera.lower().startswith("bearer ") else ""
        registro = None
        if token:
            h = huella(token)
            registro = TokenAgente.objects.select_related("usuario").filter(huella=h, activo=True).first()
            if registro is not None and not hmac.compare_digest(registro.huella, h):
                registro = None
        if registro is None or not registro.usuario.is_active:
            return _json({"error": "Token inválido o ausente."}, 401)
        if not registro.ultimo_uso or timezone.now() - registro.ultimo_uso > timedelta(minutes=5):
            TokenAgente.objects.filter(pk=registro.pk).update(ultimo_uso=timezone.now())
        request.user = registro.usuario
        try:
            return vista(request, *args, **kwargs)
        except S.ErrorConsulta as e:
            return _json({"error": str(e)}, e.estado)
    return require_GET(envoltura)


def _base(request):
    return request.build_absolute_uri("/").rstrip("/")


def _respuesta(request, mes, datos):
    return _json({**S.contexto(mes, _base(request)), **datos})


@con_token
def resumen(request):
    mes = S.elegir_mes(request.GET.get("mes"))
    return _respuesta(request, mes, S.resumen(request.user, mes))


@con_token
def buscar_clientes(request):
    mes = S.elegir_mes(None)
    return _respuesta(request, mes, S.buscar_clientes(request.user, request.GET.get("nombre", "")))


@con_token
def cliente(request, cliente_id):
    mes = S.elegir_mes(request.GET.get("mes"))
    return _respuesta(request, mes, S.cliente(request.user, cliente_id, mes))


@con_token
def criticos(request):
    mes = S.elegir_mes(request.GET.get("mes"))
    return _respuesta(request, mes, S.criticos(request.user, mes))


@con_token
def top(request):
    mes = S.elegir_mes(request.GET.get("mes"))
    try:
        n = int(request.GET.get("n", 10))
    except ValueError:
        n = 10
    return _respuesta(request, mes, S.top(request.user, mes, n))


@con_token
def glosario(request):
    return _json({**S.contexto(S.elegir_mes(None), _base(request)), **S.glosario()})


class ChatAgenteView(LoginRequiredMixin, TemplateView):
    """Pestaña «Agente Sura»: página con solo el chat del agente. Mismas reglas que la burbuja del asistente."""

    template_name = "agente/chat.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and _asistente(request.user) is None:
            raise PermissionDenied("El agente no está disponible para este usuario.")
        return super().dispatch(request, *args, **kwargs)
