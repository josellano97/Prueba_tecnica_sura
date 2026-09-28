"""
Lógica de negocio del tablero (calculada en el servidor; el navegador solo dibuja).

Todas las cifras se calculan aquí, en el servidor, a partir de los clientes que el usuario tiene
permitido ver. El navegador solo recibe el resultado agregado y lo dibuja. Las reglas son las mismas
del tablero original para que los números no cambien:

* Tasa de incidencia = casos del mes / trabajadores activos del mes x 100.
* Clasificación: crítico si tasa > umbral crítico; moderado si tasa >= umbral moderado; bajo en otro caso.
* Variación: mes de análisis vs mes inmediatamente anterior.
* Promedio histórico: promedio mensual de todos los meses disponibles hasta el mes de análisis.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ..models import Cliente, ConfiguracionTablero, IndicadorMensual

MESES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGO = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
               "octubre", "noviembre", "diciembre"]
CLASES = [1, 2, 3, 4, 5]


def etiqueta_corta(p: date) -> str:
    return f"{MESES_CORTO[p.month - 1]} {p.year}"


def etiqueta_larga(p: date) -> str:
    return f"{MESES_LARGO[p.month - 1]} de {p.year}"


def clientes_visibles(usuario):
    """Alcance de datos del usuario (equivalente al RLS de Power BI).

    * Con permiso `ver_todos_los_clientes`: todos los clientes.
    * Si no, solo los clientes del coordinador asociado a su perfil.
    * Sin coordinador asociado: ningún cliente.
    """
    if not usuario.is_authenticated or not usuario.has_perm("tablero.ver_tablero"):
        return Cliente.objects.none()
    if usuario.has_perm("tablero.ver_todos_los_clientes"):
        return Cliente.objects.all()
    coordinador_id = getattr(getattr(usuario, "perfil", None), "coordinador_id", None)
    if coordinador_id is None:
        return Cliente.objects.none()
    return Cliente.objects.filter(coordinador_id=coordinador_id)


def periodos_disponibles() -> list[date]:
    return list(IndicadorMensual.objects.order_by("periodo").values_list("periodo", flat=True).distinct())


@dataclass
class Filtros:
    mes: date
    coordinador_id: int | None = None
    sector_id: int | None = None
    clases: list[int] = field(default_factory=lambda: list(CLASES))


def _agregado_vacio():
    return {"casos": 0, "graves": 0, "leves": 0, "costo": 0.0, "costo_leve": 0.0, "costo_grave": 0.0,
            "trabajadores": 0, "criticos": 0, "tasa": None}


def clasificar(tasa: float | None, cfg: ConfiguracionTablero) -> str:
    if tasa is None:
        return "sin_dato"
    if tasa > float(cfg.umbral_critico):
        return "critico"
    if tasa >= float(cfg.umbral_moderado):
        return "moderado"
    return "bajo"


def calcular_tablero(usuario, filtros: Filtros) -> dict:
    cfg = ConfiguracionTablero.actual()
    periodos = periodos_disponibles()
    visibles = clientes_visibles(usuario)
    clientes_qs = visibles.select_related("sector", "coordinador").filter(clase_riesgo__in=filtros.clases)
    if filtros.coordinador_id:
        clientes_qs = clientes_qs.filter(coordinador_id=filtros.coordinador_id)
    if filtros.sector_id:
        clientes_qs = clientes_qs.filter(sector_id=filtros.sector_id)
    clientes = {c.id: c for c in clientes_qs}

    idx_mes = periodos.index(filtros.mes)
    hasta = periodos[: idx_mes + 1]
    filas = IndicadorMensual.objects.filter(cliente_id__in=clientes.keys(), periodo__in=hasta).values(
        "cliente_id", "periodo", "trabajadores_activos", "casos", "casos_graves", "costo_leve", "costo_grave")

    por_mes = defaultdict(_agregado_vacio)
    por_clase_mes = defaultdict(lambda: {c: {"casos": 0, "trabajadores": 0} for c in CLASES})
    por_cliente = defaultdict(dict)                     # cliente -> periodo -> fila
    umbral = float(cfg.umbral_critico)
    for f in filas:
        a = por_mes[f["periodo"]]
        costo_leve, costo_grave = float(f["costo_leve"]), float(f["costo_grave"])
        a["casos"] += f["casos"]
        a["graves"] += f["casos_graves"]
        a["leves"] += f["casos"] - f["casos_graves"]
        a["costo_leve"] += costo_leve
        a["costo_grave"] += costo_grave
        a["trabajadores"] += f["trabajadores_activos"]
        if f["casos"] / f["trabajadores_activos"] * 100 > umbral:
            a["criticos"] += 1
        clase = clientes[f["cliente_id"]].clase_riesgo
        por_clase_mes[f["periodo"]][clase]["casos"] += f["casos"]
        por_clase_mes[f["periodo"]][clase]["trabajadores"] += f["trabajadores_activos"]
        por_cliente[f["cliente_id"]][f["periodo"]] = f
    for a in por_mes.values():
        a["costo"] = a["costo_leve"] + a["costo_grave"]
        a["tasa"] = a["casos"] / a["trabajadores"] * 100 if a["trabajadores"] else None

    mes = filtros.mes
    anterior = periodos[idx_mes - 1] if idx_mes > 0 else None
    actual = por_mes.get(mes, _agregado_vacio())
    previo = por_mes.get(anterior, _agregado_vacio()) if anterior else None

    # Tendencia: 12 meses que terminan en el mes de análisis + promedio histórico de cada métrica
    ventana = periodos[max(0, idx_mes - 11): idx_mes + 1]
    tendencia = [{"periodo": p.isoformat(), "etiqueta": etiqueta_corta(p), "etiqueta_larga": etiqueta_larga(p),
                  **{k: por_mes.get(p, _agregado_vacio())[k] for k in ("casos", "graves", "costo", "tasa")}}
                 for p in ventana]
    historico = [por_mes.get(p, _agregado_vacio()) for p in hasta]

    def promedio(clave):
        valores = [h[clave] for h in historico if h[clave] is not None]
        return sum(valores) / len(valores) if valores else 0

    clases = []
    for c in CLASES:
        d = por_clase_mes[mes][c] if mes in por_clase_mes else {"casos": 0, "trabajadores": 0}
        clases.append({"clase": c, "casos": d["casos"], "trabajadores": d["trabajadores"], "activa": c in filtros.clases,
                       "tasa": d["casos"] / d["trabajadores"] * 100 if d["trabajadores"] else None})

    return {
        "mes": {"valor": mes.isoformat(), "etiqueta": etiqueta_larga(mes), "corta": etiqueta_corta(mes)},
        "mes_anterior": {"valor": anterior.isoformat(), "etiqueta": etiqueta_larga(anterior),
                         "corta": etiqueta_corta(anterior)} if anterior else None,
        "alcance": {"visibles": visibles.count(), "filtrados": len(clientes),
                    "restringido": not usuario.has_perm("tablero.ver_todos_los_clientes")},
        "umbrales": {"critico": float(cfg.umbral_critico), "moderado": float(cfg.umbral_moderado)},
        "kpis": {"actual": actual, "anterior": previo},
        "tendencia": tendencia,
        "promedio_historico": {"casos": promedio("casos"), "costo": promedio("costo"), "tasa": promedio("tasa"),
                               "meses": len(historico)},
        "por_clase": clases,
        "top": {"mes": top_clientes(clientes, por_cliente, [mes], anterior, cfg),
                "12m": top_clientes(clientes, por_cliente, ventana, None, cfg)},
    }


def top_clientes(clientes, por_cliente, periodos, anterior, cfg, limite=10) -> list[dict]:
    """Top de clientes por casos en los periodos dados (desempate por costo). Tasa = promedio mensual."""
    filas = []
    for cid, meses in por_cliente.items():
        datos = [meses[p] for p in periodos if p in meses]
        if not datos:
            continue
        casos = sum(d["casos"] for d in datos)
        trab = sum(d["trabajadores_activos"] for d in datos)
        costo = sum(float(d["costo_leve"]) + float(d["costo_grave"]) for d in datos)
        tasa = casos / trab * 100 if trab else None
        c = clientes[cid]
        fila = {"id": cid, "nombre": c.nombre, "sector": c.sector.nombre,
                "coordinador": c.coordinador.nombre if c.coordinador else "Sin coordinador",
                "clase": c.clase_riesgo, "casos": casos, "graves": sum(d["casos_graves"] for d in datos),
                "costo": costo, "tasa": tasa, "estado": clasificar(tasa, cfg)}
        if anterior is not None:
            fila["casos_anterior"] = meses[anterior]["casos"] if anterior in meses else 0
        filas.append(fila)
    filas.sort(key=lambda f: (-f["casos"], -f["costo"]))
    return filas[:limite]
