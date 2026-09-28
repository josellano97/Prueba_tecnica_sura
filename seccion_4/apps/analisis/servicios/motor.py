"""
Orquestador del análisis gerencial: obtiene el cubo una vez, ejecuta todos los análisis y guarda el
resultado en caché. La clave de caché incluye la carga de datos vigente, la configuración (umbrales),
el alcance del usuario y los filtros: si cualquiera cambia, se recalcula; si no, se reutiliza.
"""
from __future__ import annotations

import hashlib

from django.core.cache import cache

from apps.tablero.models import CargaDatos, ConfiguracionTablero
from apps.tablero.servicios.indicadores import Filtros

from . import alertas as alertas_srv
from . import anomalias, cambio, comparaciones, concentracion, explicacion, resumen
from .datos import agregar, desplazar, filas_en, obtener_cubo, ventana
from .estadistica import tendencia_lineal
from .kpis import disponibles, no_disponibles

DURACION_CACHE = 600
MAX_ALERTAS = 6


def clave_cache(usuario, filtros: Filtros, prefijo="analisis") -> str:
    carga = CargaDatos.vigente()
    cfg = ConfiguracionTablero.actual()
    alcance = "todos" if usuario.has_perm("tablero.ver_todos_los_clientes") else \
        f"coord{getattr(getattr(usuario, 'perfil', None), 'coordinador_id', None)}"
    base = (f"{prefijo}|{carga.pk if carga else 0}|{carga.creada.timestamp() if carga else 0}|{cfg.actualizado.timestamp()}|{cfg.umbral_critico}|{cfg.umbral_moderado}|"
            f"{alcance}|{filtros.mes}|{filtros.coordinador_id}|{filtros.sector_id}|{','.join(map(str, filtros.clases))}")
    return prefijo + ":" + hashlib.sha256(base.encode()).hexdigest()[:32]


def analizar(usuario, filtros: Filtros) -> dict:
    clave = clave_cache(usuario, filtros)
    resultado = cache.get(clave)
    if resultado is None:
        resultado = _calcular(usuario, filtros)
        cache.set(clave, resultado, DURACION_CACHE)
    return resultado


def _calcular(usuario, filtros: Filtros) -> dict:
    mes = filtros.mes
    cubo = obtener_cubo(usuario, filtros, hasta=mes)
    a = {"cubo": cubo, "mes": mes, "mes_anterior": desplazar(mes, -1), "mes_anio_anterior": desplazar(mes, -12),
         "ventana3": ventana(mes, 3), "ventana12": ventana(mes, 12), "filtros": filtros}
    if not cubo.filas or mes not in cubo.por_periodo:
        a["vacio"] = True
        return a
    a["vacio"] = False
    a["kpis"] = {k.clave: comparaciones.comparar(cubo, k, mes) for k in disponibles(cubo)}
    a["kpis_no_disponibles"] = no_disponibles(cubo)
    a["serie"] = anomalias.serie_con_anomalias(cubo, mes, 24)
    a["meses_anomalos"] = [s for s in a["serie"] if s["anomalia"]]
    a["descomposicion_mes"] = explicacion.descomponer(cubo, [mes], [desplazar(mes, -1)])
    a["descomposicion_anual"] = explicacion.descomponer(cubo, [mes], [desplazar(mes, -12)])
    a["contrib_sector"] = explicacion.contribuciones(cubo, "sector", [mes], [desplazar(mes, -1)])
    a["contrib_cliente"] = explicacion.contribuciones(cubo, "cliente", [mes], [desplazar(mes, -1)])
    a["cambio_mes"] = cambio.analizar(cubo, mes, cambio.normalizar(None, None, None, None))
    a["pareto_costo"] = concentracion.pareto(cubo, a["ventana12"], "cliente", "costo")
    doce = agregar(filas_en(cubo, a["ventana12"]), cubo)
    a["graves_12m"] = {"pct_casos": doce.graves / doce.casos if doce.casos else None,
                       "pct_costo": doce.costo_grave / doce.costo if doce.costo else None,
                       "costo_caso_grave": doce.costo_grave / doce.graves if doce.graves else None,
                       "costo_caso_leve": (doce.costo - doce.costo_grave) / (doce.casos - doce.graves)
                       if doce.casos > doce.graves else None}
    a["pareto_casos"] = concentracion.pareto(cubo, a["ventana12"], "cliente", "casos")
    a["sobre_clase"] = concentracion.sobre_representacion(cubo, a["ventana12"], "clase")
    a["sobre_sector"] = concentracion.sobre_representacion(cubo, a["ventana12"], "sector")
    a["anomalias"] = {
        "clientes": anomalias.segmentos_anomalos(cubo, mes, "cliente"),
        "sectores": anomalias.segmentos_anomalos(cubo, mes, "sector"),
        "mejoras": anomalias.segmentos_anomalos(cubo, mes, "cliente", direccion="abajo"),
    }
    a["persistentes"] = anomalias.persistentes(cubo, mes, "sector")
    a["criticos_recurrentes"] = anomalias.criticos_recurrentes(cubo, mes)
    a["sin_prevencion"] = anomalias.sin_prevencion_en_riesgo(cubo, mes)
    a["asociacion_prevencion"] = explicacion.asociacion_prevencion(cubo, a["ventana12"])
    a["texto_prevencion"] = (
        "Esta diferencia es consistente con un efecto protector de la prevención, pero no lo prueba: los clientes que "
        "reciben prevención pueden diferir en otros aspectos. Para medir su efecto se necesita un diseño comparativo."
        if a["asociacion_prevencion"] else None)
    a["tendencias_sector"] = _tendencias_sector(cubo, mes)
    hallazgos = (cubo.carga.calidad.get("hallazgos", []) if cubo.carga else [])
    a["calidad_critica"] = [h for h in hallazgos if h["severidad"] == "critico"]
    a["calidad_relevante"] = [h for h in hallazgos if h["severidad"] in ("critico", "advertencia")]
    todas = alertas_srv.construir(a)
    a["alertas_todas"] = todas
    a["alertas"] = todas[:MAX_ALERTAS]
    a["alertas_restantes"] = todas[MAX_ALERTAS:]
    a["resumen"] = resumen.construir(a)
    return a


def _tendencias_sector(cubo, mes):
    salida = []
    ids = {(c.sector_id, c.sector) for c in cubo.clientes.values()}
    for sid, nombre in sorted(ids, key=lambda x: x[1]):
        valores, ultimo = [], None
        for p in ventana(mes, 12):
            fs = [f for f in cubo.por_periodo.get(p, []) if cubo.clientes[f.cliente].sector_id == sid]
            c, t = sum(f.casos for f in fs), sum(f.trab for f in fs)
            valores.append(c / t * 100 if t else None)
            ultimo = valores[-1]
        salida.append({"id": sid, "nombre": nombre, "serie": valores, "tasa_actual": ultimo,
                       "tendencia": tendencia_lineal(valores)})
    return salida
