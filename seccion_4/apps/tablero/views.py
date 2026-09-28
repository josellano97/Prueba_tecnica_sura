"""
Vistas del tablero. Cada vista exige sesión (LoginRequiredMixin) y permiso (PermissionRequiredMixin):
aunque alguien conozca la URL, Django responde con redirección al login o 403 si no tiene el permiso.
"""
import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import TemplateView, UpdateView

from .forms import FiltroTableroForm
from .models import ConfiguracionTablero
from .servicios.indicadores import CLASES, calcular_tablero, clientes_visibles


class TableroView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = "tablero/tablero.html"
    permission_required = "tablero.ver_tablero"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = FiltroTableroForm(usuario=self.request.user)
        ctx.update({
            "periodos": list(reversed(form.fields["mes"].choices)),
            "coordinadores": form.fields["coordinador"].queryset,
            "sectores": form.fields["sector"].queryset,
            "clases": CLASES,
            "sin_alcance": not clientes_visibles(self.request.user).exists(),
            "puede_exportar": self.request.user.has_perm("tablero.exportar_datos"),
            "configuracion": ConfiguracionTablero.actual(),
            "hay_datos": bool(form.periodos),
        })
        return ctx


class _ConFiltros(LoginRequiredMixin, PermissionRequiredMixin, View):
    raise_exception = True          # a las peticiones de datos no se les redirige: se responde 403

    def filtros_o_error(self, request):
        form = FiltroTableroForm(request.GET, usuario=request.user)
        if not form.periodos:
            return None, JsonResponse({"error": "No hay datos cargados."}, status=404)
        if not form.is_valid():
            return None, JsonResponse({"error": "Filtros inválidos.", "detalle": form.errors}, status=400)
        return form.filtros(), None


class DatosTableroView(_ConFiltros):
    """API JSON que alimenta los gráficos. Respeta el alcance de clientes del usuario."""

    permission_required = "tablero.ver_tablero"

    def get(self, request):
        filtros, error = self.filtros_o_error(request)
        if error:
            return error
        return JsonResponse(calcular_tablero(request.user, filtros))


class ExportarTopView(_ConFiltros):
    """Descarga en CSV (compatible con Excel) del top 10 de clientes con los filtros aplicados."""

    permission_required = ("tablero.ver_tablero", "tablero.exportar_datos")

    def get(self, request):
        filtros, error = self.filtros_o_error(request)
        if error:
            return error
        periodo = "12m" if request.GET.get("periodo") == "12m" else "mes"
        datos = calcular_tablero(request.user, filtros)
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = f'attachment; filename="top10_clientes_{filtros.mes:%Y_%m}_{periodo}.csv"'
        respuesta.write("﻿")                         # BOM para que Excel reconozca UTF-8
        w = csv.writer(respuesta, delimiter=";")
        w.writerow(["posicion", "cliente", "sector", "coordinador", "clase_riesgo", "casos", "graves", "tasa",
                    "costo", "estado"])
        for i, f in enumerate(datos["top"][periodo], 1):
            tasa = "" if f["tasa"] is None else f"{f['tasa']:.2f}".replace(".", ",")
            w.writerow([i, _seguro(f["nombre"]), _seguro(f["sector"]), _seguro(f["coordinador"]), f["clase"],
                        f["casos"], f["graves"], tasa, round(f["costo"]), f["estado"]])
        return respuesta


def _seguro(texto: str) -> str:
    """Evita inyección de fórmulas al abrir el CSV en Excel (=, +, -, @ al inicio)."""
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


class ConfiguracionView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Parámetros del tablero. Ver requiere view_configuraciontablero; guardar, change_configuraciontablero."""

    permission_required = "tablero.view_configuraciontablero"
    template_name = "tablero/configuracion.html"
    fields = ["nombre_organizacion", "umbral_moderado", "umbral_critico"]
    success_url = reverse_lazy("tablero:configuracion")

    def get_object(self, queryset=None):
        return ConfiguracionTablero.actual()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["puede_editar"] = self.request.user.has_perm("tablero.change_configuraciontablero")
        return ctx

    def post(self, request, *args, **kwargs):
        if not request.user.has_perm("tablero.change_configuraciontablero"):
            raise PermissionDenied
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        messages.success(self.request, "Configuración guardada. Los cambios ya se aplican en el tablero.")
        return super().form_valid(form)
