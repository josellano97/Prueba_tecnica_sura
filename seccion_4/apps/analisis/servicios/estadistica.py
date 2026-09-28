"""
Estadística mínima necesaria, sin dependencias externas.

* Prueba de Poisson para conteos de casos: dado un nivel esperado (exposición x tasa de referencia),
  ¿qué tan improbable es observar tantos (o tan pocos) casos por azar? Es la prueba adecuada para
  eventos poco frecuentes medidos sobre una exposición conocida, y evita alertar por ruido.
* Tendencia lineal (mínimos cuadrados) con estadístico t: solo se afirma que algo "sube" o "baja"
  si la pendiente es claramente distinta de cero (|t| >= 2, aproximadamente 95 %).
"""
from __future__ import annotations

import math


def _log_pmf(k: int, lam: float) -> float:
    return k * math.log(lam) - lam - math.lgamma(k + 1)


def poisson_cola_superior(k: int, lam: float) -> float:
    """P(X >= k) con X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    tope = int(k + 12 * math.sqrt(max(lam, k)) + 60)
    return min(1.0, sum(math.exp(_log_pmf(j, lam)) for j in range(k, tope)))


def poisson_cola_inferior(k: int, lam: float) -> float:
    """P(X <= k) con X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0
    if k < 0:
        return 0.0
    inicio = max(0, int(k - 12 * math.sqrt(max(lam, 1)) - 60))
    return min(1.0, sum(math.exp(_log_pmf(j, lam)) for j in range(inicio, k + 1)))


def comparar_conteo(observado: int, esperado: float) -> dict:
    """Compara casos observados con los esperados. Devuelve dirección y p-valor de una cola."""
    if esperado <= 0:
        return {"direccion": "sin_referencia", "p": None, "exceso": observado, "razon": None}
    if observado >= esperado:
        p, direccion = poisson_cola_superior(observado, esperado), "arriba"
    else:
        p, direccion = poisson_cola_inferior(observado, esperado), "abajo"
    return {"direccion": direccion, "p": p, "exceso": observado - esperado, "razon": observado / esperado}


def nivel_significancia(p: float | None) -> str:
    if p is None:
        return "sin_prueba"
    if p < 0.001:
        return "muy_alta"
    if p < 0.01:
        return "alta"
    if p < 0.05:
        return "moderada"
    return "no_significativa"


def tendencia_lineal(valores: list[float]) -> dict | None:
    """Pendiente por periodo, pendiente relativa al promedio y estadístico t."""
    pares = [(i, v) for i, v in enumerate(valores) if v is not None]
    n = len(pares)
    if n < 6:
        return None
    xs, ys = [p[0] for p in pares], [p[1] for p in pares]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    pendiente = sum((x - mx) * (y - my) for x, y in pares) / sxx
    residuos = [y - (my + pendiente * (x - mx)) for x, y in pares]
    s2 = sum(r * r for r in residuos) / (n - 2)
    error = math.sqrt(s2 / sxx) if s2 > 0 else 0.0
    t = pendiente / error if error > 0 else (math.inf if pendiente else 0.0)
    if abs(t) >= 2:
        direccion = "sube" if pendiente > 0 else "baja"
    else:
        direccion = "estable"
    return {"pendiente": pendiente, "pendiente_rel": pendiente / my if my else None, "t": t,
            "direccion": direccion, "n": n}


def variacion_relativa(actual, referencia):
    if actual is None or referencia in (None, 0):
        return None
    return (actual - referencia) / referencia
