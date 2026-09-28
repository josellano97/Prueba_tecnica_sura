"""
Nivel 3 · ¿Dónde exactamente está el problema? Drill-down con contexto:

    Total  →  dimensión (sector | clase | regional | coordinador)  →  cliente  →  mes  →  casos

En cada nivel, cada fila trae lo mismo: casos, exposición, tasa, cuántos casos serían esperables según
su propio historial (y si la diferencia es significativa), variación vs mes anterior, costo y
contribución a la variación total. Así el gerente ordena por "dónde hay más casos de lo normal".
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from apps.tablero.models import Caso

from .anomalias import EXPOSICION_REF, _tasas_clase
from .datos import Cubo, agregar, desplazar, ventana
from .estadistica import comparar_conteo, nivel_significancia
from .explicacion import DIMENSIONES

DIMENSIONES_DRILL = ["sector", "clase", "regional", "coordinador"]


def _filas_miembro(cubo, predicado):
    return [f for f in cubo.filas if predicado(cubo.clientes[f.cliente])]


def tabla(cubo: Cubo, mes: date, dimension: str, predicado=lambda info: True) -> list[dict]:
    _, clave = DIMENSIONES[dimension]
    ant, base = desplazar(mes, -1), ventana(desplazar(mes, -1), 12)
    doce = ventana(mes, 12)
    tasa_clase = _tasas_clase(cubo, base) if dimension == "cliente" else {}
    grupos = defaultdict(lambda: defaultdict(list))
    for f in cubo.filas:
        info = cubo.clientes[f.cliente]
        if predicado(info):
            grupos[clave(info)][f.periodo].append(f)
    total_delta = 0
    filas = []
    for (ident, nombre), por_p in grupos.items():
        act = agregar(por_p.get(mes, []), cubo) if mes in por_p else None
        if act is None:
            continue
        prev = agregar(por_p.get(ant, []), cubo) if ant in por_p else None
        b = [f for p in base for f in por_p.get(p, [])]
        bc, bt = sum(f.casos for f in b), sum(f.trab for f in b)
        if dimension == "cliente":
            rc = tasa_clase.get(cubo.clientes[ident].clase)
            tasa_ref = (bc + EXPOSICION_REF * rc / 100) / (bt + EXPOSICION_REF) * 100 if rc is not None else None
        else:
            tasa_ref = bc / bt * 100 if bt else None
        esperado = act.trab * tasa_ref / 100 if tasa_ref is not None else None
        prueba = comparar_conteo(act.casos, esperado) if esperado else None
        serie = []
        for p in doce:
            fs = por_p.get(p, [])
            c, t = sum(f.casos for f in fs), sum(f.trab for f in fs)
            serie.append(c / t * 100 if t else None)
        delta = act.casos - (prev.casos if prev else 0)
        total_delta += delta
        filas.append({
            "id": ident, "nombre": nombre, "casos": act.casos, "trab": act.trab, "tasa": act.casos / act.trab * 100,
            "casos_ant": prev.casos if prev else None, "delta": delta, "costo": act.costo,
            "pct_graves": act.graves / act.casos if act.casos else None, "criticos": act.criticos,
            "clientes": act.clientes, "prev_cobertura": (act.clientes_con_prev / act.clientes) if act.clientes_con_prev is not None else None,
            "tasa_ref": tasa_ref, "esperado": esperado, "exceso": act.casos - esperado if esperado is not None else None,
            "p": prueba["p"] if prueba else None, "significancia": nivel_significancia(prueba["p"]) if prueba else "sin_prueba",
            "direccion": prueba["direccion"] if prueba else None, "serie": serie,
            "estado": ("critico" if act.casos / act.trab * 100 > cubo.umbral_critico else
                       "moderado" if act.casos / act.trab * 100 >= cubo.umbral_moderado else "bajo") if dimension == "cliente" else None,
        })
    movimiento = sum(abs(f["delta"]) for f in filas)
    for f in filas:
        # participación en el movimiento total (suma de cambios absolutos): con un neto cercano a cero,
        # el % sobre el neto se dispara y no se puede leer
        f["contrib"] = f["delta"] / movimiento if movimiento else None
    filas.sort(key=lambda r: -(r["exceso"] if r["exceso"] is not None else -1e9))
    return filas


def perfil_cliente(cubo: Cubo, cliente_id: int, mes: date) -> dict | None:
    info = cubo.clientes.get(cliente_id)
    if info is None:
        return None
    por_p = {f.periodo: f for f in cubo.filas if f.cliente == cliente_id}
    meses = []
    for p in ventana(mes, 24):
        f = por_p.get(p)
        if f is None:
            meses.append({"periodo": p, "sin_datos": True})
            continue
        tasa = f.casos / f.trab * 100
        meses.append({"periodo": p, "trab": f.trab, "casos": f.casos, "graves": f.graves, "tasa": tasa, "costo": f.costo,
                      "dias": f.dias, "prev": f.prev, "abiertos": f.abiertos,
                      "estado": "critico" if tasa > cubo.umbral_critico else "moderado" if tasa >= cubo.umbral_moderado else "bajo"})
    doce = [m for m in meses[-12:] if not m.get("sin_datos")]
    resumen = {
        "casos_12m": sum(m["casos"] for m in doce), "costo_12m": sum(m["costo"] for m in doce),
        "tasa_12m": sum(m["casos"] for m in doce) / sum(m["trab"] for m in doce) * 100 if doce else None,
        "meses_criticos_12m": sum(1 for m in doce if m["estado"] == "critico"),
        "prev_12m": sum(m["prev"] for m in doce) if cubo.tiene("prevencion") and doce else None,
    }
    casos = []
    if "detalle_casos" in (cubo.carga.variables if cubo.carga else []):
        fin = desplazar(mes, 1)
        casos = list(Caso.objects.filter(cliente_id=cliente_id, fecha__gte=mes, fecha__lt=fin)
                     .order_by("-costo").values("id_origen", "fecha", "tipo", "dias_ausencia", "costo", "estado"))
    return {"info": info, "meses": meses, "resumen": resumen, "casos_mes": casos}
