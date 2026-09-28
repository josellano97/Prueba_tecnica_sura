"""
Vistas del análisis gerencial. La lógica vive en servicios/; aquí solo se validan filtros, se aplica el
permiso y se arma el contexto de la plantilla. Mismo control de acceso y alcance que el tablero.
"""
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import Http404
from django.views.generic import TemplateView

from apps.tablero.forms import FiltroTableroForm
from apps.tablero.models import CargaDatos, ConfiguracionTablero

from .servicios import cambio
from .servicios import diagnostico as diag
from .servicios import motor
from .servicios.datos import obtener_cubo, ventana
from .servicios.explicacion import DIMENSIONES
from .servicios.faltantes import OPORTUNIDADES
from .servicios.kpis import CATALOGO


class _BaseAnalisis(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = ("tablero.ver_tablero", "tablero.ver_analisis")

    def filtros(self):
        form = FiltroTableroForm(self.request.GET or None, usuario=self.request.user)
        self.form = form
        if not form.periodos:
            return None
        if self.request.GET and not form.is_valid():
            raise Http404("Filtros inválidos")
        if not self.request.GET:
            form.cleaned_data = {}
        return form.filtros()

    def contexto_filtros(self, f):
        qs = {"mes": f.mes.isoformat()[:7]}
        if f.coordinador_id:
            qs["coordinador"] = f.coordinador_id
        if f.sector_id:
            qs["sector"] = f.sector_id
        if len(f.clases) < 5:
            qs["clase"] = f.clases
        return {
            "f": f, "form": self.form, "periodos": list(reversed(self.form.fields["mes"].choices)),
            "coordinadores": self.form.fields["coordinador"].queryset, "sectores": self.form.fields["sector"].queryset,
            "qs": urlencode(qs, doseq=True), "clases": [1, 2, 3, 4, 5],
        }


class ResumenView(_BaseAnalisis):
    template_name = "analisis/resumen.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        f = self.filtros()
        if f is None:
            ctx["sin_datos"] = True
            return ctx
        a = motor.analizar(self.request.user, f)
        ctx.update(self.contexto_filtros(f))
        ctx["a"] = a
        if not a.get("vacio"):
            k = a["kpis"]
            ctx["nivel1"] = [k[c] for c in ("tasa", "casos", "costo", "severidad", "criticos", "cobertura_prevencion") if c in k]
            ctx["nivel2"] = [v for v in k.values() if v["kpi"].nivel == 2]
            # Qué revisar: solo prioridad alta; el resto queda contado y disponible en el diagnóstico
            ctx["alertas_altas"] = [x for x in a["alertas_todas"] if x.nivel == "alta"]
            ctx["n_alertas_media"] = len(a["alertas_todas"]) - len(ctx["alertas_altas"])
            # ¿Por qué cambió?: periodo, comparación, dimensión y medida elegibles (cálculo liviano sobre el cubo en caché)
            g = self.request.GET
            opciones = cambio.normalizar(g.get("periodo"), g.get("comp"), g.get("por"), g.get("medida"))
            ctx["cambio"] = cambio.analizar(a["cubo"], f.mes, opciones)
            ctx["op_cambio"] = {"periodos": cambio.PERIODOS.items(), "comparaciones": cambio.COMPARACIONES.items(),
                                "por": [(d, DIMENSIONES[d][0]) for d in cambio.POR], "medidas": cambio.MEDIDAS.items()}
            ctx["sectores_fuera"] = sorted([{**s, "dif": s["ajustado"] - 1} for s in a["sobre_sector"] if s["sig_ajustado"]],
                                           key=lambda s: -s["ajustado"])
            ctx["persistir"] = [(k, g[k]) for k in ("periodo", "comp", "por", "medida") if g.get(k)]
        return ctx


class DiagnosticoView(_BaseAnalisis):
    template_name = "analisis/diagnostico.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        f = self.filtros()
        if f is None:
            ctx["sin_datos"] = True
            return ctx
        ctx.update(self.contexto_filtros(f))
        dim = self.request.GET.get("dim", "sector")
        if dim not in diag.DIMENSIONES_DRILL:
            raise Http404
        cubo = obtener_cubo(self.request.user, f, hasta=f.mes)
        valor = self.request.GET.get("valor")
        cliente = self.request.GET.get("cliente")
        _, clave = DIMENSIONES[dim]
        miga = [{"texto": "Total", "url": f"?{ctx['qs']}&dim={dim}"}]
        ctx.update({"dim": dim, "dimensiones": [(d, DIMENSIONES[d][0]) for d in diag.DIMENSIONES_DRILL],
                    "nombre_dim": DIMENSIONES[dim][0], "cubo": cubo})
        predicado = lambda info: True  # noqa: E731
        if valor is not None:
            miembro = next((clave(i) for i in cubo.clientes.values() if str(clave(i)[0]) == valor), None)
            if miembro is None:
                raise Http404
            predicado = lambda info: str(clave(info)[0]) == valor  # noqa: E731
            miga.append({"texto": f"{DIMENSIONES[dim][0]}: {miembro[1]}", "url": f"?{ctx['qs']}&dim={dim}&valor={valor}"})
            ctx["miembro"] = miembro
        if cliente is not None:
            if not cliente.isdigit():
                raise Http404
            perfil = diag.perfil_cliente(cubo, int(cliente), f.mes)
            if perfil is None or not predicado(perfil["info"]):
                raise Http404                     # fuera del alcance del usuario o de la jerarquía
            miga.append({"texto": perfil["info"].nombre, "url": ""})
            ctx.update({"perfil": perfil, "nivel": "cliente"})
        elif valor is not None:
            ctx.update({"filas": diag.tabla(cubo, f.mes, "cliente", predicado), "nivel": "clientes",
                        "base_url": f"?{ctx['qs']}&dim={dim}&valor={valor}&cliente="})
        else:
            ctx.update({"filas": diag.tabla(cubo, f.mes, dim), "nivel": "dimension",
                        "base_url": f"?{ctx['qs']}&dim={dim}&valor="})
        ctx["miga"] = miga
        return ctx


class CalidadView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = ("tablero.ver_analisis", "tablero.ver_calidad_datos")
    template_name = "analisis/calidad.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        carga = CargaDatos.vigente()
        ctx["carga"] = carga
        if carga:
            orden = {"critico": 0, "advertencia": 1, "info": 2}
            ctx["hallazgos"] = sorted(carga.calidad.get("hallazgos", []), key=lambda h: orden.get(h["severidad"], 3))
            ctx["resumen"] = carga.calidad.get("resumen", {})
            etiquetas = {"clientes": "Clientes", "casos_leidos": "Casos leídos en la fuente",
                         "casos_validos_en_indicadores": "Casos válidos en los indicadores",
                         "registros_mensuales": "Registros cliente × mes", "actividades_prevencion": "Actividades de prevención"}
            ctx["resumen_legible"] = [(etiquetas.get(k, k), v) for k, v in ctx["resumen"].items() if k in etiquetas]
            ctx["conteo"] = {s: sum(1 for h in ctx["hallazgos"] if h["severidad"] == s) for s in orden}
        return ctx


class MetodologiaView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    permission_required = ("tablero.ver_analisis",)
    template_name = "analisis/metodologia.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        carga = CargaDatos.vigente()
        variables = set(carga.variables) if carga else set()
        mapa = {"dias": "dias_ausencia", "prevencion": "actividades_prevencion", "valor": "valor_contrato", "abiertos": "casos_abiertos"}
        ctx.update({"catalogo": [{"kpi": k, "disponible": k.requiere is None or mapa.get(k.requiere) in variables}
                                 for k in CATALOGO],
                    "faltantes": OPORTUNIDADES, "carga": carga, "cfg": ConfiguracionTablero.actual()})
        return ctx
