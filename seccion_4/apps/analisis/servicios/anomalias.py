"""
Detección de anomalías y patrones (hechos observados con prueba estadística, no interpretaciones).

Idea común: para cada mes y segmento se calcula cuántos casos serían ESPERABLES con su exposición actual y
su propio nivel de riesgo reciente (12 meses previos), y se mide qué tan improbable es lo observado
(prueba de Poisson). Solo se reporta como anomalía lo que es muy poco probable por azar (p < 0,01).

* serie_con_anomalias: picos y caídas del total mes a mes (marcas en la tendencia).
* segmentos_anomalos: clientes/sectores con casos muy por encima de lo esperable en el mes.
  En clientes, la tasa de referencia se "suaviza" hacia la de su clase de riesgo (300 trabajadores-mes,
  mismo criterio de la consulta SQL 2.2) para que un cliente pequeño no aparezca por un solo caso.
* persistentes: segmentos por encima de lo esperable en cada uno de los últimos 3 meses (cambio sostenido).
* criticos_recurrentes: clientes críticos (regla oficial) en al menos 3 de los últimos 6 meses.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .datos import Cubo, desplazar, filas_en, ventana
from .estadistica import comparar_conteo, nivel_significancia
from .explicacion import DIMENSIONES

UMBRAL_P = 0.01
EXPOSICION_REF = 300.0


def _tasa(casos, trab):
    return casos / trab * 100 if trab else None


def serie_con_anomalias(cubo: Cubo, hasta: date, n: int = 24) -> list[dict]:
    salida = []
    for p in ventana(hasta, n):
        filas = cubo.por_periodo.get(p, [])
        casos, trab = sum(f.casos for f in filas), sum(f.trab for f in filas)
        base = filas_en(cubo, ventana(desplazar(p, -1), 12))
        bc, bt = sum(f.casos for f in base), sum(f.trab for f in base)
        punto = {"periodo": p, "casos": casos, "trab": trab, "tasa": _tasa(casos, trab),
                 "costo": sum(f.costo for f in filas), "anomalia": None}
        meses_base = len({f.periodo for f in base})
        if filas and meses_base >= 12 and bt:
            esperado = trab * bc / bt
            r = comparar_conteo(casos, esperado)
            punto.update({"esperado": esperado, "p": r["p"]})
            if r["p"] is not None and r["p"] < UMBRAL_P:
                punto["anomalia"] = "pico" if r["direccion"] == "arriba" else "caida"
        salida.append(punto)
    return salida


def _por_segmento(cubo: Cubo, periodos, dimension):
    _, clave = DIMENSIONES[dimension]
    g = defaultdict(lambda: [0, 0])
    for f in filas_en(cubo, periodos):
        k = clave(cubo.clientes[f.cliente])
        g[k][0] += f.casos
        g[k][1] += f.trab
    return g


def _tasas_clase(cubo: Cubo, periodos):
    g = defaultdict(lambda: [0, 0])
    for f in filas_en(cubo, periodos):
        c = cubo.clientes[f.cliente].clase
        g[c][0] += f.casos; g[c][1] += f.trab
    return {c: v[0] / v[1] * 100 for c, v in g.items() if v[1]}


def segmentos_anomalos(cubo: Cubo, mes: date, dimension: str, direccion: str = "arriba") -> list[dict]:
    base_periodos = ventana(desplazar(mes, -1), 12)
    act = _por_segmento(cubo, [mes], dimension)
    base = _por_segmento(cubo, base_periodos, dimension)
    tasa_clase = _tasas_clase(cubo, base_periodos) if dimension == "cliente" else {}
    salida = []
    for k, (casos, trab) in act.items():
        if not trab:
            continue
        bc, bt = base.get(k, (0, 0))
        if dimension == "cliente":
            ref_clase = tasa_clase.get(cubo.clientes[k[0]].clase)
            if ref_clase is None:
                continue
            tasa_ref = (bc + EXPOSICION_REF * ref_clase / 100) / (bt + EXPOSICION_REF) * 100
        else:
            if bt < 1000:                         # historial insuficiente para una referencia estable
                continue
            tasa_ref = bc / bt * 100
        esperado = trab * tasa_ref / 100
        r = comparar_conteo(casos, esperado)
        if r["p"] is None or r["p"] >= UMBRAL_P or r["direccion"] != direccion:
            continue
        if direccion == "arriba" and casos - esperado < 2:
            continue
        salida.append({"id": k[0], "nombre": k[1], "dimension": dimension, "casos": casos, "esperado": esperado,
                       "exceso": casos - esperado, "razon": r["razon"], "p": r["p"],
                       "significancia": nivel_significancia(r["p"]), "tasa": casos / trab * 100, "tasa_ref": tasa_ref,
                       "trab": trab})
    salida.sort(key=lambda s: -abs(s["exceso"]))
    return salida


def persistentes(cubo: Cubo, mes: date, dimension: str = "sector", meses: int = 3) -> list[dict]:
    """Segmentos con más casos de lo esperable en cada uno de los últimos `meses` meses y en conjunto (p < 0,05)."""
    ultimos = ventana(mes, meses)
    base_periodos = ventana(desplazar(ultimos[0], -1), 12)
    base = _por_segmento(cubo, base_periodos, dimension)
    por_mes = [_por_segmento(cubo, [p], dimension) for p in ultimos]
    salida = []
    for k in por_mes[-1]:
        bc, bt = base.get(k, (0, 0))
        if bt < 1000:
            continue
        ref = bc / bt
        obs = [pm.get(k, (0, 0)) for pm in por_mes]
        if not all(t and c > t * ref for c, t in obs):
            continue
        c_tot, t_tot = sum(c for c, _ in obs), sum(t for _, t in obs)
        r = comparar_conteo(c_tot, t_tot * ref)
        if r["p"] is not None and r["p"] < 0.05:
            salida.append({"id": k[0], "nombre": k[1], "dimension": dimension, "meses": meses, "casos": c_tot,
                           "esperado": t_tot * ref, "exceso": c_tot - t_tot * ref, "p": r["p"],
                           "significancia": nivel_significancia(r["p"]), "tasa_ref": ref * 100,
                           "tasa": c_tot / t_tot * 100})
    salida.sort(key=lambda s: -s["exceso"])
    return salida


def criticos_recurrentes(cubo: Cubo, mes: date, minimo: int = 3, meses: int = 6) -> list[dict]:
    periodos = ventana(mes, meses)
    conteo = defaultdict(list)
    for p in periodos:
        for f in cubo.por_periodo.get(p, []):
            if f.trab and f.casos / f.trab * 100 > cubo.umbral_critico:
                conteo[f.cliente].append(p)
    salida = []
    for cid, ps in conteo.items():
        if len(ps) >= minimo:
            filas = [f for p in periodos for f in cubo.por_periodo.get(p, []) if f.cliente == cid]
            casos, trab = sum(f.casos for f in filas), sum(f.trab for f in filas)
            info = cubo.clientes[cid]
            salida.append({"id": cid, "nombre": info.nombre, "sector": info.sector, "clase": info.clase,
                           "coordinador": info.coordinador, "meses_criticos": len(ps), "de": meses,
                           "en_mes_actual": mes in ps, "tasa_periodo": casos / trab * 100 if trab else None,
                           "casos_mes": sum(f.casos for f in cubo.por_periodo.get(mes, []) if f.cliente == cid),
                           "trab_promedio": trab / len(filas) if filas else 0,
                           "prevencion": sum(f.prev for f in filas) if cubo.tiene("prevencion") else None})
    ref = _tasas_clase(cubo, ventana(desplazar(mes, -1), 12))
    for s in salida:
        f_mes = [f for f in cubo.por_periodo.get(mes, []) if f.cliente == s["id"]]
        s["exceso_mes"] = sum(f.casos - f.trab * ref.get(s["clase"], 0) / 100 for f in f_mes)
    salida.sort(key=lambda s: (-s["meses_criticos"], -(s["tasa_periodo"] or 0)))
    return salida


def sin_prevencion_en_riesgo(cubo: Cubo, mes: date, meses: int = 3) -> list[dict]:
    """Clientes críticos o moderados en el mes, sin ninguna actividad de prevención en los últimos `meses` meses."""
    if not cubo.tiene("prevencion"):
        return []
    periodos = ventana(mes, meses)
    prev = defaultdict(int)
    for f in filas_en(cubo, periodos):
        prev[f.cliente] += f.prev
    salida = []
    ref = _tasas_clase(cubo, ventana(desplazar(mes, -1), 12))
    for f in cubo.por_periodo.get(mes, []):
        tasa = _tasa(f.casos, f.trab)
        if tasa is not None and tasa >= cubo.umbral_moderado and prev[f.cliente] == 0:
            info = cubo.clientes[f.cliente]
            salida.append({"id": f.cliente, "nombre": info.nombre, "clase": info.clase, "sector": info.sector,
                           "coordinador": info.coordinador, "tasa": tasa, "casos": f.casos, "trab": f.trab,
                           "exceso": f.casos - f.trab * ref.get(info.clase, 0) / 100,
                           "estado": "critico" if tasa > cubo.umbral_critico else "moderado"})
    salida.sort(key=lambda s: -s["tasa"])
    return salida
