import logging

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

log = logging.getLogger("seguridad")


def inicio(request):
    """La raíz lleva al análisis gerencial (la página principal); sin ese permiso, al tablero.
    Sin sesión, la página de destino envía al login."""
    if request.user.is_authenticated and not request.user.has_perm("tablero.ver_analisis"):
        return redirect("tablero:inicio")
    return redirect("analisis:resumen")


def favicon(request):
    """Los navegadores piden /favicon.ico aunque la página no lo declare (p. ej. el admin)."""
    return redirect(static("img/favicon.png"), permanent=True)


@never_cache
@require_GET
def salud(request):
    """Sondeo de salud para Azure App Service: responde 200 si la aplicación y la base de datos responden."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"estado": "ok"})
    except Exception:  # noqa: BLE001 - el detalle se registra, no se expone
        log.exception("Falla del sondeo de salud")
        return JsonResponse({"estado": "error"}, status=503)


def error_403(request, exception=None):
    if request.user.is_authenticated:
        log.warning("Acceso denegado: usuario=%s ruta=%s", request.user.get_username(), request.path)
    return render(request, "errores/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errores/404.html", status=404)


def error_500(request):
    return render(request, "errores/500.html", status=500)
