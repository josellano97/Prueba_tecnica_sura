"""
Nivel 2 · ¿Por qué cambió el resultado? Descomposiciones exactas (los efectos suman la variación total).

1. Casos = exposición × tasa. Δcasos = (T1 − T0)·r0 + T1·(r1 − r0)
   → cuánto se debe a tener más/menos trabajadores y cuánto a un cambio real de riesgo.
2. Tasa total = Σ (peso de cada clase de riesgo × tasa de la clase).
   Δtasa = Σ (w1 − w0)·r0  [mezcla de cartera]  +  Σ w1·(r1 − r0)  [cambio dentro de las clases]
   → si la tasa sube porque la cartera tiene más clientes de alto riesgo o porque cada clase empeoró.
3. Costo = casos × costo por caso. Δcosto = Δcasos·c0 + casos1·(c1 − c0)
   → si el costo sube por más casos o por casos más caros.
4. Contribución de cada miembro de una dimensión (sector, cliente...) a la variación de casos y costo.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .datos import Cubo, agregar, filas_en


def _grupos(filas, clave):
    g = defaultdict(list)
    for f in filas:
        g[clave(f)].append(f)
    return g


def descomponer(cubo: Cubo, actual: list[date], base: list[date]) -> dict | None:
    """Compara dos ventanas de igual número de meses (p. ej. mes vs mes anterior, o 3 meses vs 3 meses)."""
    f1, f0 = filas_en(cubo, actual), filas_en(cubo, base)
    if not f1 or not f0:
        return None
    a1, a0 = agregar(f1, cubo), agregar(f0, cubo)
    r1, r0 = a1.casos / a1.trab * 100, a0.casos / a0.trab * 100
    casos = {"total": a1.casos - a0.casos, "exposicion": (a1.trab - a0.trab) * r0 / 100,
             "riesgo": a1.trab * (r1 - r0) / 100, "t0": a0.trab, "t1": a1.trab, "r0": r0, "r1": r1}

    clase = lambda f: cubo.clientes[f.cliente].clase  # noqa: E731
    g1, g0 = _grupos(f1, clase), _grupos(f0, clase)
    mezcla = intra = 0.0
    detalle_clases = []
    for c in sorted(set(g1) | set(g0)):
        t1 = sum(f.trab for f in g1.get(c, [])); t0 = sum(f.trab for f in g0.get(c, []))
        k1 = sum(f.casos for f in g1.get(c, [])); k0 = sum(f.casos for f in g0.get(c, []))
        w1, w0 = t1 / a1.trab, t0 / a0.trab
        rc1 = k1 / t1 * 100 if t1 else 0.0
        rc0 = k0 / t0 * 100 if t0 else rc1
        m, i = (w1 - w0) * rc0, w1 * (rc1 - rc0)
        mezcla += m; intra += i
        detalle_clases.append({"clase": c, "peso0": w0, "peso1": w1, "tasa0": rc0, "tasa1": rc1, "mezcla": m, "intra": i})
    tasa = {"total": r1 - r0, "mezcla": mezcla, "intra": intra, "clases": detalle_clases}

    c1 = a1.costo / a1.casos if a1.casos else 0.0
    c0 = a0.costo / a0.casos if a0.casos else 0.0
    costo = {"total": a1.costo - a0.costo, "volumen": (a1.casos - a0.casos) * c0, "costo_por_caso": a1.casos * (c1 - c0),
             "c0": c0, "c1": c1}
    return {"casos": casos, "tasa": tasa, "costo": costo, "a1": a1, "a0": a0}


DIMENSIONES = {
    "sector": ("Sector", lambda info: (info.sector_id, info.sector)),
    "clase": ("Clase de riesgo", lambda info: (info.clase, f"Clase {info.clase}")),
    "regional": ("Regional", lambda info: (info.regional, info.regional)),
    "coordinador": ("Coordinador", lambda info: (info.coordinador_id or 0, info.coordinador)),
    "cliente": ("Cliente", lambda info: (info.id, info.nombre)),
}


def contribuciones(cubo: Cubo, dimension: str, actual: list[date], base: list[date]) -> list[dict]:
    """Variación de casos y costo por miembro de la dimensión, con su participación en la variación total."""
    _, clave = DIMENSIONES[dimension]
    llave = lambda f: clave(cubo.clientes[f.cliente])  # noqa: E731
    g1, g0 = _grupos(filas_en(cubo, actual), llave), _grupos(filas_en(cubo, base), llave)
    total_casos = sum(f.casos for fs in g1.values() for f in fs) - sum(f.casos for fs in g0.values() for f in fs)
    total_costo = sum(f.costo for fs in g1.values() for f in fs) - sum(f.costo for fs in g0.values() for f in fs)
    filas = []
    for k in set(g1) | set(g0):
        k1 = sum(f.casos for f in g1.get(k, [])); k0 = sum(f.casos for f in g0.get(k, []))
        c1 = sum(f.costo for f in g1.get(k, [])); c0 = sum(f.costo for f in g0.get(k, []))
        filas.append({"id": k[0], "nombre": k[1], "casos1": k1, "casos0": k0, "delta_casos": k1 - k0,
                      "costo1": c1, "costo0": c0, "delta_costo": c1 - c0,
                      # sin facturación en una de las dos ventanas: cliente nuevo o que salió (explica saltos desde 0)
                      "solo_actual": k not in g0, "solo_base": k not in g1,
                      "part_casos": (k1 - k0) / total_casos if total_casos else None,
                      "part_costo": (c1 - c0) / total_costo if total_costo else None})
    filas.sort(key=lambda r: -abs(r["delta_casos"]))
    return filas


def asociacion_prevencion(cubo: Cubo, periodos: list[date]) -> dict | None:
    """Tasa de los meses-cliente CON vs SIN prevención en los 3 meses previos, dentro de cada clase de riesgo.

    Es una asociación observada, no una prueba de causalidad (los clientes que reciben prevención pueden
    ser distintos en otros aspectos). Se estratifica por clase para no confundir el efecto del riesgo base.
    """
    if not cubo.tiene("prevencion"):
        return None
    indice = {(f.cliente, f.periodo): f for f in cubo.filas}
    from .datos import desplazar
    grupos = defaultdict(lambda: {"con": [0, 0], "sin": [0, 0]})
    for p in periodos:
        for f in cubo.por_periodo.get(p, []):
            previos = [indice.get((f.cliente, desplazar(p, -i))) for i in (1, 2, 3)]
            if any(x is None for x in previos):
                continue
            g = "con" if sum(x.prev for x in previos) > 0 else "sin"
            celda = grupos[cubo.clientes[f.cliente].clase][g]
            celda[0] += f.casos; celda[1] += f.trab
    clases = []
    ponderado, peso = 0.0, 0
    for c in sorted(grupos):
        con, sin = grupos[c]["con"], grupos[c]["sin"]
        if con[1] < 500 or sin[1] < 500:                 # exposición mínima para comparar (trabajadores-mes)
            continue
        tc, ts = con[0] / con[1] * 100, sin[0] / sin[1] * 100
        clases.append({"clase": c, "tasa_con": tc, "tasa_sin": ts, "exp_con": con[1], "exp_sin": sin[1],
                       "diferencia": (tc - ts) / ts if ts else None})
        ponderado += (tc - ts) / ts * (con[1] + sin[1]) if ts else 0
        peso += con[1] + sin[1]
    if not clases:
        return None
    return {"clases": clases, "diferencia_ponderada": ponderado / peso if peso else None}
