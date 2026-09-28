"""
¿Por qué cambió? con periodo, comparación, dimensión y medida elegibles por el usuario.

Las dos ventanas siempre tienen el mismo número de meses (mes vs mes, 3 vs 3, año corrido vs mismo tramo del
año anterior, 12 vs 12), así las descomposiciones de explicacion.py siguen siendo exactas.
"""
from __future__ import annotations

from datetime import date

from . import formato as F
from .datos import Cubo, desplazar, ventana
from .estadistica import comparar_conteo, nivel_significancia
from .explicacion import DIMENSIONES, contribuciones, descomponer

PERIODOS = {"mes": "Mes", "trimestre": "Últimos 3 meses", "ytd": "Año corrido", "12m": "Últimos 12 meses"}
COMPARACIONES = {"anterior": "Periodo inmediatamente anterior", "anio": "Mismo periodo del año anterior"}
MEDIDAS = {"casos": "Casos", "costo": "Costo"}
POR = ["sector", "clase", "regional", "coordinador", "cliente"]
MAX_FILAS = 8


def normalizar(periodo, comp, por, medida) -> dict:
    """Valores válidos (lo desconocido vuelve al valor por defecto). Año corrido y 12 meses solo se comparan
    con el año anterior: el 'periodo anterior' de 12 meses es el mismo año anterior."""
    periodo = periodo if periodo in PERIODOS else "mes"
    comp = comp if comp in COMPARACIONES else "anterior"
    if periodo in ("ytd", "12m"):
        comp = "anio"
    return {"periodo": periodo, "comp": comp, "por": por if por in POR else "sector",
            "medida": medida if medida in MEDIDAS else "casos"}


def ventanas(mes: date, periodo: str, comp: str) -> tuple[list[date], list[date]]:
    if periodo == "ytd":
        actual = [date(mes.year, m, 1) for m in range(1, mes.month + 1)]
    else:
        actual = ventana(mes, {"mes": 1, "trimestre": 3, "12m": 12}[periodo])
    n = len(actual)
    base = [desplazar(p, -12) for p in actual] if comp == "anio" else ventana(desplazar(actual[0], -1), n)
    return actual, base


def etiqueta(periodos: list[date]) -> str:
    if len(periodos) == 1:
        return F.mes(periodos[0])
    a, b = periodos[0], periodos[-1]
    if a.year == b.year:
        return f"{F.MESES_C[a.month - 1]}–{F.MESES_C[b.month - 1]} {b.year}"
    return f"{F.mes(a, True)} – {F.mes(b, True)}"


def analizar(cubo: Cubo, mes: date, opciones: dict) -> dict:
    actual, base = ventanas(mes, opciones["periodo"], opciones["comp"])
    salida = {"opciones": opciones, "actual": etiqueta(actual), "base": etiqueta(base), "disponible": False}
    faltan = [p for p in base if p not in cubo.por_periodo]
    if faltan:
        salida["motivo"] = f"No hay datos de {etiqueta(base)} para comparar (los datos empiezan en {F.mes(cubo.periodos[0])})."
        return salida
    d = descomponer(cubo, actual, base)
    if d is None:
        salida["motivo"] = "Sin datos para esta selección."
        return salida
    c = d["casos"]
    # ¿el cambio de riesgo es real? casos observados vs los esperables con la tasa del periodo base
    prueba = comparar_conteo(d["a1"].casos, d["a1"].trab * c["r0"] / 100)
    sig = nivel_significancia(prueba["p"]) if prueba else "sin_prueba"
    significativo = sig in ("muy_alta", "alta")

    clave = "delta_casos" if opciones["medida"] == "casos" else "delta_costo"
    filas = [x for x in contribuciones(cubo, opciones["por"], actual, base) if x[clave]]
    filas.sort(key=lambda x: -abs(x[clave]))
    top, resto = filas[:MAX_FILAS], filas[MAX_FILAS:]
    maximo = max((abs(x[clave]) for x in top), default=0)
    for x in top:
        x["delta"] = x[clave]
        x["ancho"] = f"{abs(x[clave]) / maximo * 100 if maximo else 0:.1f}"   # punto decimal para CSS
    salida.update({
        "disponible": True, "d": d, "significativo": significativo, "p": prueba["p"] if prueba else None,
        "lectura": _lectura(d, significativo), "filas": top, "medida": opciones["medida"],
        "resto": {"n": len(resto), "delta": sum(x[clave] for x in resto)} if resto else None,
        "nombre_por": DIMENSIONES[opciones["por"]][0],
    })
    return salida


def _lectura(d, significativo) -> str:
    """Una frase: qué explica el cambio de casos (hecho) y si el cambio de riesgo es estadísticamente real."""
    c = d["casos"]
    if c["total"] == 0:
        return "Los casos no cambiaron."
    if abs(c["exposicion"]) >= abs(c["riesgo"]):
        motor = f"principalmente por {'más' if c['exposicion'] > 0 else 'menos'} trabajadores"
    else:
        motor = f"principalmente porque la tasa {'subió' if c['riesgo'] > 0 else 'bajó'}"
    riesgo = ("el cambio de la tasa es estadísticamente significativo" if significativo
              else "el cambio de la tasa está dentro de la variación normal")
    return f"Los casos {'subieron' if c['total'] > 0 else 'bajaron'} en {F.num(abs(c['total']))}, {motor}; {riesgo}."
