"""
Resumen ejecutivo: como máximo cuatro hechos, los más importantes para decidir, más una línea de límites.

  1. Estado      ¿el mes es normal frente a su propio historial? (prueba de Poisson)
  2. Cambio      ¿qué explica la variación frente al mes anterior? (exposición vs riesgo)
  3. Atención    ¿qué sector está significativamente por encima de lo esperable este mes?
  4. Estructura  ¿qué sector tiene más casos de lo que explica su riesgo en 12 meses? (o la concentración del costo)

Solo hechos verificables; las hipótesis quedan en las alertas y en el detalle, nunca en el resumen.
"""
from __future__ import annotations

from . import formato as F


def _punto(tono, titulo, texto):
    return {"tipo": "hecho", "tono": tono, "titulo": titulo, "texto": texto}


def construir(a) -> dict:
    k, mes = a["kpis"], a["mes"]
    tasa, casos = k["tasa"], k["casos"]
    puntos = []

    # 1. Estado
    estado = tasa["juicio"]["estado"]
    ref = tasa["referencias"]["promedio_12m"]["valor"]
    lectura = {"peor": "por encima de su nivel habitual", "mejor": "por debajo de su nivel habitual",
               "normal": "dentro de su nivel habitual"}.get(estado, "sin historial para comparar")
    texto = f"{F.num(casos['valor'])} casos y tasa de {F.num(tasa['valor'], 2)} por cada 100 trabajadores: {lectura}"
    texto += f" ({F.num(ref, 2)} en los 12 meses previos)." if ref is not None else "."
    puntos.append(_punto({"peor": "alerta", "mejor": "ok", "normal": "ok"}.get(estado, "info"), "Estado del mes", texto))

    # 2. Cambio frente al mes anterior
    cm = a.get("cambio_mes")
    if cm and cm["disponible"]:
        puntos.append(_punto("alerta" if cm["significativo"] and cm["d"]["casos"]["riesgo"] > 0 else "info",
                             f"Frente a {F.mes(a['mes_anterior'])}", cm["lectura"]))

    # 3. Atención este mes: sector significativamente por encima de lo esperable
    sectores = a["anomalias"]["sectores"]
    if sectores:
        s = sectores[0]
        otros = f" También: {', '.join(x['nombre'] for x in sectores[1:3])}." if len(sectores) > 1 else ""
        puntos.append(_punto("alerta", "Dónde mirar",
                             f"{s['nombre']}: {F.num(s['casos'])} casos frente a {F.num(s['esperado'], 1)} esperables "
                             f"(probabilidad de azar {F.num(s['p'] * 100, 2)} %).{otros}"))
    else:
        puntos.append(_punto("ok", "Dónde mirar", "Ningún sector está significativamente por encima de lo esperable este mes."))

    # 4. Estructura de 12 meses
    arriba = sorted([s for s in a["sobre_sector"] if s["sig_ajustado"] and s["ajustado"] > 1], key=lambda s: -s["ajustado"])
    pc = a["pareto_costo"]
    if arriba:
        s = arriba[0]
        puntos.append(_punto("alerta", "Últimos 12 meses",
                             f"{s['nombre']} tiene {F.pct(s['ajustado'] - 1, 0)} más casos de lo que explica su clase de riesgo "
                             f"({F.num(s['casos'])} vs {F.num(s['esperado'], 0)} esperables)."))
    elif pc:
        puntos.append(_punto("info", "Últimos 12 meses",
                             f"{pc['n_corte']} de {pc['n']} clientes concentran el 80 % del costo."))

    # Límites de la lectura (una sola línea)
    limites = ["No existen metas oficiales: se compara con el propio historial"]
    if a["cubo"].carga and a["cubo"].carga.fuente == "demo":
        limites.append("datos de demostración sin severidad, prevención ni detalle de casos")
    n_calidad = len(a["calidad_relevante"])
    if n_calidad:
        limites.append(f"{n_calidad} advertencia{'s' if n_calidad > 1 else ''} de calidad de datos")
    return {"puntos": puntos[:4], "advertencia": {"tipo": "advertencia", "texto": "; ".join(limites) + "."}}
