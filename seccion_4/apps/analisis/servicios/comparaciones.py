"""
Comparaciones temporales de cada KPI y prueba de significancia.

Referencias (solo las que existen en los datos):
  * mes anterior
  * mismo mes del año anterior (controla la estacionalidad: jul/ago altos, dic bajo)
  * promedio de los 12 meses previos (sin incluir el mes analizado)
  * acumulado del año vs mismo acumulado del año anterior
La significancia se prueba solo donde tiene sentido estadístico: en la tasa y los casos (conteos de
Poisson sobre una exposición conocida). Para montos y porcentajes se reporta la variación sin prueba.
"""
from __future__ import annotations

from datetime import date

from .datos import Cubo, agregar, desplazar, filas_en, ventana
from .estadistica import comparar_conteo, nivel_significancia, tendencia_lineal, variacion_relativa
from .kpis import KPI


def agregado_mes(cubo: Cubo, p: date):
    if p not in cubo.por_periodo:
        return None
    return agregar(cubo.por_periodo[p], cubo)


def agregado_ventana(cubo: Cubo, periodos: list[date]):
    presentes = [p for p in periodos if p in cubo.por_periodo]
    if not presentes:
        return None
    return agregar(filas_en(cubo, presentes), cubo, meses=len(presentes))


def serie(cubo: Cubo, kpi: KPI, hasta: date, n: int) -> list[dict]:
    return [{"periodo": p, "valor": kpi.valor(agregado_mes(cubo, p))} for p in ventana(hasta, n)]


def _prueba_casos(act, ref_tasa):
    """Casos observados del mes vs esperados si el riesgo fuera el de referencia (misma exposición)."""
    if act is None or ref_tasa is None or not act.trab:
        return None
    esperado = act.trab * ref_tasa / 100
    r = comparar_conteo(act.casos, esperado)
    r["esperado"] = esperado
    r["significancia"] = nivel_significancia(r["p"])
    return r


def comparar(cubo: Cubo, kpi: KPI, mes: date) -> dict:
    act = agregado_mes(cubo, mes)
    ant = agregado_mes(cubo, desplazar(mes, -1))
    anio_ant = agregado_mes(cubo, desplazar(mes, -12))
    base12 = agregado_ventana(cubo, ventana(desplazar(mes, -1), 12))
    ytd = agregado_ventana(cubo, [date(mes.year, m, 1) for m in range(1, mes.month + 1)])
    ytd_ant = agregado_ventana(cubo, [date(mes.year - 1, m, 1) for m in range(1, mes.month + 1)])
    v = kpi.valor(act)
    refs = {
        "mes_anterior": kpi.valor(ant),
        "anio_anterior": kpi.valor(anio_ant),
        "promedio_12m": kpi.valor(base12),
    }
    resultado = {
        "kpi": kpi, "valor": v,
        "referencias": {k: {"valor": r, "variacion": variacion_relativa(v, r)} for k, r in refs.items()},
        "ytd": {"valor": kpi.valor(ytd), "anterior": kpi.valor(ytd_ant),
                "variacion": variacion_relativa(kpi.valor(ytd), kpi.valor(ytd_ant)),
                "meses": ytd.meses if ytd else 0} if kpi.agregacion != "promedio_mensual" else None,
        "serie": serie(cubo, kpi, mes, 24),
        "pruebas": {},
    }
    resultado["serie_valores"] = [s["valor"] for s in resultado["serie"][-12:]]
    t12 = tendencia_lineal(resultado["serie_valores"])
    resultado["tendencia"] = t12
    if kpi.clave in ("tasa", "casos"):
        tasa = lambda a: a.casos / a.trab * 100 if a and a.trab else None  # noqa: E731
        resultado["pruebas"] = {
            "mes_anterior": _prueba_casos(act, tasa(ant)),
            "anio_anterior": _prueba_casos(act, tasa(anio_ant)),
            "promedio_12m": _prueba_casos(act, tasa(base12)),
        }
    resultado["juicio"] = juicio(kpi, resultado)
    return resultado


def juicio(kpi: KPI, r: dict) -> dict:
    """Lectura de la situación del KPI frente a su propio historial (no frente a una meta, que no existe)."""
    if not kpi.comparable:
        return {"estado": "foto", "texto": "Foto a la fecha de corte: no es comparable entre periodos."}
    var12 = r["referencias"]["promedio_12m"]["variacion"]
    prueba = r["pruebas"].get("promedio_12m")
    if var12 is None:
        return {"estado": "sin_referencia", "texto": "Sin historial suficiente para comparar."}
    if kpi.sentido == "neutro":
        return {"estado": "neutro", "texto": "Indicador descriptivo."}
    peor = (var12 > 0) if kpi.sentido == "baja" else (var12 < 0)
    if prueba is not None:
        significativo = prueba["significancia"] in ("muy_alta", "alta", "moderada")
        motivo = " (diferencia estadísticamente significativa)."
    else:
        # Sin prueba formal: se compara con la variabilidad propia del KPI en sus 12 meses previos.
        z = z_historico(r)
        significativo = z is not None and abs(z) >= 2
        motivo = " (a más de 2 desviaciones de su variación habitual)."
    if not significativo:
        return {"estado": "normal", "texto": "Dentro de su rango habitual."}
    return {"estado": "peor" if peor else "mejor",
            "texto": ("Peor" if peor else "Mejor") + " que su nivel habitual" + motivo}


def z_historico(r: dict) -> float | None:
    previos = [s["valor"] for s in r["serie"][-13:-1] if s["valor"] is not None]
    if len(previos) < 6 or r["valor"] is None:
        return None
    media = sum(previos) / len(previos)
    desv = (sum((x - media) ** 2 for x in previos) / (len(previos) - 1)) ** 0.5
    return (r["valor"] - media) / desv if desv else None
