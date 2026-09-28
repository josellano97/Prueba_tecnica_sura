"""
¿Dónde se concentra el resultado? Pareto y sobre-representación.

* Pareto: ordena clientes (o sectores) por costo/casos y calcula qué fracción de ellos explica el 80 %.
* Sobre-representación: participación en los casos ÷ participación en los trabajadores. Un valor de 1,5
  significa que el segmento aporta 50 % más casos de lo que le correspondería por su tamaño.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .datos import Cubo, filas_en
from .estadistica import comparar_conteo
from .explicacion import DIMENSIONES


def pareto(cubo: Cubo, periodos: list[date], dimension: str = "cliente", medida: str = "costo", corte: float = 0.8) -> dict | None:
    _, clave = DIMENSIONES[dimension]
    tot = defaultdict(float)
    for f in filas_en(cubo, periodos):
        tot[clave(cubo.clientes[f.cliente])] += f.costo if medida == "costo" else f.casos
    elementos = sorted(((k, v) for k, v in tot.items()), key=lambda x: -x[1])
    total = sum(v for _, v in elementos)
    if not elementos or total <= 0:
        return None
    acum, curva, n_corte = 0.0, [], None
    for i, ((ident, nombre), v) in enumerate(elementos, 1):
        acum += v
        curva.append({"id": ident, "nombre": nombre, "valor": v, "part": v / total, "acum": acum / total})
        if n_corte is None and acum / total >= corte:
            n_corte = i
    con_valor = sum(1 for _, v in elementos if v > 0)
    return {"medida": medida, "dimension": dimension, "total": total, "n": len(elementos), "n_con_valor": con_valor,
            "n_corte": n_corte, "pct_elementos": n_corte / len(elementos), "corte": corte,
            "top": curva[:10], "curva": [c["acum"] for c in curva],
            "part_top10pct": sum(c["valor"] for c in curva[:max(1, round(len(curva) * 0.1))]) / total}


def sobre_representacion(cubo: Cubo, periodos: list[date], dimension: str) -> list[dict]:
    _, clave = DIMENSIONES[dimension]
    casos, trab, costo = defaultdict(int), defaultdict(int), defaultdict(float)
    filas_p = filas_en(cubo, periodos)
    # tasa de cada clase de riesgo en toda la cartera (para la razón estandarizada)
    cc, tc_ = defaultdict(int), defaultdict(int)
    for f in filas_p:
        c = cubo.clientes[f.cliente].clase
        cc[c] += f.casos; tc_[c] += f.trab
    tasa_clase = {c: cc[c] / tc_[c] for c in cc if tc_[c]}
    esperado = defaultdict(float)
    for f in filas_p:
        k = clave(cubo.clientes[f.cliente])
        casos[k] += f.casos; trab[k] += f.trab; costo[k] += f.costo
        esperado[k] += f.trab * tasa_clase.get(cubo.clientes[f.cliente].clase, 0)
    tc, tt, tco = sum(casos.values()), sum(trab.values()), sum(costo.values())
    if not tc or not tt:
        return []
    filas = [{"id": k[0], "nombre": k[1], "casos": casos[k], "trab_mes": trab[k], "costo": costo[k],
              "part_casos": casos[k] / tc, "part_trab": trab[k] / tt, "part_costo": costo[k] / tco if tco else None,
              "tasa": casos[k] / trab[k] * 100 if trab[k] else None,
              "indice": (casos[k] / tc) / (trab[k] / tt) if trab[k] else None,
              "esperado": esperado[k], "ajustado": casos[k] / esperado[k] if esperado[k] else None,
              "p_ajustado": comparar_conteo(casos[k], esperado[k])["p"] if esperado[k] else None} for k in casos]
    for r in filas:
        r["sig_ajustado"] = dimension != "clase" and r["p_ajustado"] is not None and r["p_ajustado"] < 0.01
    filas.sort(key=lambda r: -(r["part_casos"]))
    return filas
