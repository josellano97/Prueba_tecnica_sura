"""
Respuestas del agente conversacional. Reutilizan los mismos cálculos del tablero (tablero/servicios/indicadores.py),
así el agente siempre da los mismos números que la aplicación. Cada respuesta trae la fecha de corte, el mes
analizado y las cifras ya escritas en español para que el modelo de lenguaje no tenga que formatearlas.
"""
from __future__ import annotations

import unicodedata
from datetime import date

from apps.analisis.servicios import formato as F
from apps.analisis.servicios.kpis import POR_CLAVE
from apps.tablero.models import CargaDatos, ConfiguracionTablero, IndicadorMensual
from apps.tablero.servicios.indicadores import (
    Filtros, calcular_tablero, clasificar, clientes_visibles, etiqueta_larga, periodos_disponibles,
)

ESTADOS = {"critico": "crítico", "moderado": "moderado", "bajo": "bajo", "sin_dato": "sin dato"}


class ErrorConsulta(Exception):
    """Pregunta que no se puede responder (mes inexistente, cliente fuera del alcance…)."""

    def __init__(self, mensaje, estado=400):
        super().__init__(mensaje)
        self.estado = estado


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _var(actual, anterior):
    if actual is None or not anterior:
        return None
    return (actual - anterior) / anterior


def _tasa_texto(t):
    return "sin dato" if t is None else F.num(t, 2)


def elegir_mes(valor: str | None) -> date:
    """Mes pedido (AAAA-MM) o, por defecto, el último mes cerrado con datos."""
    periodos = periodos_disponibles()
    if not periodos:
        raise ErrorConsulta("No hay datos cargados.", 404)
    if not valor:
        return periodos[-1]
    try:
        mes = date.fromisoformat(valor.strip()[:7] + "-01")
    except ValueError as e:
        raise ErrorConsulta("El mes debe venir como AAAA-MM, por ejemplo 2026-08.") from e
    if mes not in periodos:
        raise ErrorConsulta(f"No hay datos de {etiqueta_larga(mes)}. Hay meses cerrados desde "
                            f"{etiqueta_larga(periodos[0])} hasta {etiqueta_larga(periodos[-1])}.", 404)
    return mes


def contexto(mes: date, base_url: str) -> dict:
    carga = CargaDatos.vigente()
    ultimo = periodos_disponibles()[-1]
    return {
        "mes_analizado": mes.isoformat()[:7], "mes_analizado_texto": etiqueta_larga(mes),
        "fecha_corte": carga.fecha_corte.isoformat() if carga else None,
        "nota": (f"Los datos llegan hasta el {carga.fecha_corte:%d/%m/%Y}. El último mes cerrado es "
                 f"{etiqueta_larga(ultimo)}; el mes en curso está incompleto y no se reporta.") if carga else "",
        "enlace_tablero": f"{base_url}/tablero/?mes={mes.isoformat()[:7]}",
    }


# ------------------------------------------------------------------ consultas
def resumen(usuario, mes: date) -> dict:
    d = calcular_tablero(usuario, Filtros(mes=mes))
    act, ant = d["kpis"]["actual"], d["kpis"]["anterior"] or {}
    return {
        "alcance": f"{d['alcance']['filtrados']} clientes" + (" (solo su cartera)" if d["alcance"]["restringido"] else ""),
        "casos": act["casos"], "casos_graves": act["graves"], "trabajadores": act["trabajadores"],
        "trabajadores_texto": F.num(act["trabajadores"]),
        "costo": round(act["costo"]), "costo_texto": F.cop(act["costo"]),
        "tasa": act["tasa"], "tasa_texto": _tasa_texto(act["tasa"]),
        "clientes_criticos": act["criticos"],
        "mes_anterior": {
            "mes": d["mes_anterior"]["etiqueta"] if d["mes_anterior"] else None,
            "casos": ant.get("casos"), "tasa_texto": _tasa_texto(ant.get("tasa")), "costo_texto": F.cop(ant.get("costo")),
            "variacion_casos_texto": F.pct(_var(act["casos"], ant.get("casos")), 1, signo=True),
            "variacion_tasa_texto": F.pct(_var(act["tasa"], ant.get("tasa")), 1, signo=True),
            "variacion_costo_texto": F.pct(_var(act["costo"], ant.get("costo")), 1, signo=True),
        },
        "promedio_historico_tasa_texto": _tasa_texto(d["promedio_historico"]["tasa"]),
        "por_clase_de_riesgo": [{"clase": c["clase"], "casos": c["casos"], "tasa_texto": _tasa_texto(c["tasa"])}
                                for c in d["por_clase"]],
        "top_5_clientes": [{"cliente": f["nombre"], "casos": f["casos"], "tasa_texto": _tasa_texto(f["tasa"]),
                            "estado": ESTADOS[f["estado"]]} for f in d["top"]["mes"][:5]],
    }


def buscar_clientes(usuario, texto: str) -> dict:
    texto = (texto or "").strip()
    if len(texto) < 2:
        raise ErrorConsulta("Escriba al menos 2 letras del nombre del cliente.")
    palabras = _sin_tildes(texto).split()
    encontrados = []
    for c in clientes_visibles(usuario).select_related("sector", "coordinador").order_by("nombre"):
        nombre = _sin_tildes(c.nombre)
        if all(p in nombre for p in palabras):
            encontrados.append({"id": c.id, "cliente": c.nombre, "sector": c.sector.nombre, "clase_riesgo": c.clase_riesgo,
                                "coordinador": c.coordinador.nombre if c.coordinador else "Sin coordinador",
                                "activo": c.activo})
    return {"busqueda": texto, "total": len(encontrados), "clientes": encontrados[:10],
            "nota_busqueda": "Hay más de 10 coincidencias: pida un nombre más completo." if len(encontrados) > 10 else ""}


def cliente(usuario, cliente_id: int, mes: date) -> dict:
    c = clientes_visibles(usuario).select_related("sector", "coordinador").filter(id=cliente_id).first()
    if c is None:
        raise ErrorConsulta("Ese cliente no existe o no está dentro de lo que este usuario puede ver.", 404)
    cfg = ConfiguracionTablero.actual()
    periodos = [p for p in periodos_disponibles() if p <= mes]
    filas = {f.periodo: f for f in IndicadorMensual.objects.filter(cliente=c, periodo__in=periodos[-6:])}

    def datos(p):
        f = filas.get(p)
        if f is None:
            return None
        tasa = f.casos / f.trabajadores_activos * 100 if f.trabajadores_activos else None
        return {"mes": etiqueta_larga(p), "casos": f.casos, "casos_graves": f.casos_graves,
                "trabajadores": f.trabajadores_activos, "trabajadores_texto": F.num(f.trabajadores_activos),
                "tasa": tasa, "tasa_texto": _tasa_texto(tasa),
                "costo_texto": F.cop(float(f.costo_leve) + float(f.costo_grave)),
                "nivel_de_riesgo": ESTADOS[clasificar(tasa, cfg)]}

    act = datos(mes)
    ant = datos(periodos[-2]) if len(periodos) > 1 else None
    return {
        "cliente": c.nombre, "sector": c.sector.nombre, "clase_riesgo": c.clase_riesgo,
        "coordinador": c.coordinador.nombre if c.coordinador else "Sin coordinador", "activo": c.activo,
        "mes": act or {"mes": etiqueta_larga(mes), "nota": "El cliente no tuvo facturación ese mes."},
        "mes_anterior": ant,
        "variacion_casos_texto": F.delta(act["casos"] - ant["casos"]) if act and ant else None,
        "ultimos_6_meses": [x for x in (datos(p) for p in periodos[-6:]) if x],
        "regla_nivel_de_riesgo": (f"crítico si la tasa es mayor a {F.num(cfg.umbral_critico, 2)}; moderado desde "
                                  f"{F.num(cfg.umbral_moderado, 2)}; bajo por debajo"),
    }


def criticos(usuario, mes: date) -> dict:
    cfg = ConfiguracionTablero.actual()
    visibles = clientes_visibles(usuario).select_related("sector", "coordinador")
    ids = {c.id: c for c in visibles}
    lista, moderados = [], 0
    for f in IndicadorMensual.objects.filter(cliente_id__in=ids.keys(), periodo=mes):
        tasa = f.casos / f.trabajadores_activos * 100 if f.trabajadores_activos else None
        estado = clasificar(tasa, cfg)
        if estado == "moderado":
            moderados += 1
        if estado == "critico":
            c = ids[f.cliente_id]
            lista.append({"cliente": c.nombre, "tasa": tasa, "tasa_texto": _tasa_texto(tasa), "casos": f.casos,
                          "trabajadores": f.trabajadores_activos, "trabajadores_texto": F.num(f.trabajadores_activos),
                          "clase_riesgo": c.clase_riesgo, "sector": c.sector.nombre,
                          "coordinador": c.coordinador.nombre if c.coordinador else "Sin coordinador"})
    lista.sort(key=lambda x: -x["tasa"])
    return {"clientes_criticos": lista, "total_criticos": len(lista), "total_moderados": moderados,
            "regla": f"crítico si la tasa del mes es mayor a {F.num(cfg.umbral_critico, 2)} casos por 100 trabajadores"}


def top(usuario, mes: date, n: int = 10) -> dict:
    d = calcular_tablero(usuario, Filtros(mes=mes))
    return {"top_clientes_por_casos": [
        {"posicion": i, "cliente": f["nombre"], "casos": f["casos"], "casos_graves": f["graves"],
         "tasa_texto": _tasa_texto(f["tasa"]), "costo_texto": F.cop(f["costo"]), "clase_riesgo": f["clase"],
         "nivel_de_riesgo": ESTADOS[f["estado"]], "coordinador": f["coordinador"]}
        for i, f in enumerate(d["top"]["mes"][:max(1, min(n, 10))], 1)]}


def glosario() -> dict:
    cfg = ConfiguracionTablero.actual()
    kpis = {k: POR_CLAVE[k] for k in ("tasa", "casos", "costo", "severidad", "criticos", "cobertura_prevencion")}
    return {
        "indicadores": [{"nombre": k.nombre, "que_significa": k.interpretacion, "calculo": k.formula,
                         "limitaciones": k.limitaciones} for k in kpis.values()],
        "niveles_de_riesgo": {
            "critico": f"tasa del mes mayor a {F.num(cfg.umbral_critico, 2)} casos por cada 100 trabajadores",
            "moderado": f"tasa desde {F.num(cfg.umbral_moderado, 2)} hasta {F.num(cfg.umbral_critico, 2)}",
            "bajo": f"tasa menor a {F.num(cfg.umbral_moderado, 2)}"},
        "caso_valido": "todo caso que no esté anulado; los anulados no cuentan como incidentes",
        "caso_grave": "lo define el campo tipo del caso, no los días de ausencia",
    }
