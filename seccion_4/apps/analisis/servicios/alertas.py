"""
Alertas gerenciales: pocas, priorizadas y sustentadas.

Una situación solo se convierte en alerta si es un hecho verificable en los datos Y es estadísticamente
significativa o corresponde a una regla oficial (criticidad). Se prioriza por nivel y por impacto (casos
en exceso sobre lo esperable). La pantalla muestra solo las primeras; el resto queda contado.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import formato as F

ORDEN_NIVEL = {"alta": 0, "media": 1}


@dataclass
class Alerta:
    nivel: str                   # 'alta' | 'media'
    categoria: str
    titulo: str
    hecho: str
    revisar: str
    impacto: float = 0.0         # casos en exceso sobre lo esperable (misma unidad para todas las alertas)
    grupo: int = 1               # 0 = desempeño general y calidad · 1 = situaciones puntuales · 2 = tendencias
    hipotesis: str | None = None
    enlace: dict = field(default_factory=dict)   # parámetros para el diagnóstico
    corto: str = ""              # una línea para la vista resumida (si falta se usa el título)


def construir(a) -> list[Alerta]:
    """`a` es el resultado del motor (ver motor.analizar)."""
    alertas: list[Alerta] = []
    mes, cubo = a["mes"], a["cubo"]
    tasa = a["kpis"]["tasa"]
    p12 = tasa["pruebas"].get("promedio_12m")
    pa = tasa["pruebas"].get("anio_anterior")
    if p12 and p12["direccion"] == "arriba" and p12["significancia"] in ("muy_alta", "alta"):
        extra = ""
        if pa and pa["direccion"] == "arriba" and pa["significancia"] in ("muy_alta", "alta", "moderada"):
            extra = f" También supera a {F.mes(a['mes_anio_anterior'])} (mismo mes, descarta efecto estacional)."
        alertas.append(Alerta(
            "alta", "Desempeño general", "La tasa del mes está por encima de su nivel habitual",
            f"Tasa {F.num(tasa['valor'], 2)} frente a {F.num(tasa['referencias']['promedio_12m']['valor'], 2)} de los 12 meses previos: "
            f"{F.num(p12['exceso'], 0)} casos más de lo esperable con la misma cantidad de trabajadores.{extra}",
            "Ver en el diagnóstico qué sectores y clientes explican el aumento.", p12["exceso"], grupo=0,
            enlace={"dimension": "sector"},
            corto=f"Tasa {F.num(tasa['valor'], 2)} vs {F.num(tasa['referencias']['promedio_12m']['valor'], 2)} · {F.num(p12['exceso'], 0)} casos más de lo esperable"))

    t = tasa.get("tendencia")
    if t and t["direccion"] == "sube":
        alertas.append(Alerta(
            "media", "Tendencia", "La tasa de incidencia tiene tendencia creciente en 12 meses",
            f"Pendiente de +{F.num(t['pendiente'], 3)} puntos por mes ({F.pct(t['pendiente_rel'] or 0, 1)} del promedio mensual), estadísticamente distinta de cero.",
            "Revisar si el aumento es general o de algunos sectores (tabla de tendencias por sector).", 0, grupo=2))
    for s in a["tendencias_sector"]:
        if s["tendencia"] and s["tendencia"]["direccion"] == "sube":
            alertas.append(Alerta(
                "media", "Tendencia", f"{s['nombre']}: tasa en aumento sostenido",
                f"Tendencia creciente de 12 meses estadísticamente significativa (tasa actual {F.num(s['tasa_actual'], 2)}).",
                "Revisar los clientes del sector con mayor contribución al aumento.", 0, grupo=2,
                enlace={"dimension": "sector", "sector": s["id"]}))

    for s in a["anomalias"]["sectores"][:3]:
        alertas.append(Alerta(
            "alta" if s["significancia"] == "muy_alta" else "media", "Aumento significativo",
            f"{s['nombre']}: {F.num(s['casos'])} casos en el mes, {F.num(s['exceso'])} por encima de lo esperable",
            f"Con sus trabajadores y su tasa habitual ({F.num(s['tasa_ref'], 2)}) se esperaban {F.num(s['esperado'], 1)} casos; "
            f"se registraron {F.num(s['casos'])} (tasa {F.num(s['tasa'], 2)}). Probabilidad de que sea azar: {F.num(s['p'] * 100, 2)} %.",
            "Abrir el sector en el diagnóstico para ver qué clientes lo explican.", s["exceso"],
            enlace={"dimension": "sector", "sector": s["id"]},
            corto=f"Tasa {F.num(s['tasa'], 2)} vs {F.num(s['tasa_ref'], 2)} habitual · probabilidad de azar {F.num(s['p'] * 100, 2)} %"))
    for s in a["anomalias"]["clientes"][:5]:
        info = cubo.clientes[s["id"]]
        alertas.append(Alerta(
            "alta" if s["significancia"] == "muy_alta" else "media", "Aumento significativo",
            f"{s['nombre']}: {F.num(s['casos'])} casos vs {F.num(s['esperado'], 1)} esperables",
            f"Clase {info.clase}, {info.sector}, {F.num(s['trab'])} trabajadores. Tasa del mes {F.num(s['tasa'], 2)} frente a su referencia "
            f"{F.num(s['tasa_ref'], 2)} (probabilidad de azar {F.num(s['p'] * 100, 2)} %).",
            f"Revisar los casos del mes con el coordinador ({info.coordinador}).", s["exceso"],
            enlace={"dimension": "sector", "sector": info.sector_id, "cliente": s["id"]},
            corto=f"{info.sector} · {F.num(s['trab'])} trabajadores · {info.coordinador} · probabilidad de azar {F.num(s['p'] * 100, 2)} %"))
    for s in a["persistentes"][:3]:
        alertas.append(Alerta(
            "media", "Cambio persistente", f"{s['nombre']}: tres meses seguidos por encima de su nivel",
            f"En los últimos {s['meses']} meses acumuló {F.num(s['casos'])} casos frente a {F.num(s['esperado'], 1)} esperables "
            f"(tasa {F.num(s['tasa'], 2)} vs {F.num(s['tasa_ref'], 2)} habitual).",
            "Revisar su evolución mensual y sus clientes en el diagnóstico.", s["exceso"],
            corto=f"{F.num(s['casos'])} casos vs {F.num(s['esperado'], 1)} esperables en {s['meses']} meses",
            hipotesis="Un aumento sostenido podría reflejar un cambio en la operación del sector o de sus clientes; hay que validarlo con el coordinador.",
            enlace={"dimension": "sector", "sector": s["id"]}))
    rec = [r for r in a["criticos_recurrentes"] if r["en_mes_actual"]]
    if rec:
        nombres = ", ".join(r["nombre"] for r in rec[:4]) + ("…" if len(rec) > 4 else "")
        alertas.append(Alerta(
            "alta" if any(r["meses_criticos"] >= 5 for r in rec) else "media", "Problema recurrente",
            f"{len(rec)} cliente{'s' if len(rec) > 1 else ''} crítico{'s' if len(rec) > 1 else ''} en al menos 3 de los últimos 6 meses",
            f"{nombres}. Siguen en estado crítico este mes (tasa > {F.num(cubo.umbral_critico, 1)}).",
            "Evaluar un plan de intervención para estos clientes con sus coordinadores.",
            sum(max(0, r["exceso_mes"]) for r in rec), enlace={"vista": "recurrentes"}, corto=nombres))
    sp = a["sin_prevencion"]
    if sp:
        n_crit = sum(1 for s in sp if s["estado"] == "critico")
        alertas.append(Alerta(
            "media", "Brecha de prevención",
            f"{len(sp)} cliente{'s' if len(sp) > 1 else ''} en estado crítico o moderado sin prevención en 3 meses",
            f"{n_crit} crítico{'s' if n_crit != 1 else ''} y {len(sp) - n_crit} moderado{'s' if len(sp) - n_crit != 1 else ''} este mes "
            f"no registran ninguna actividad de prevención desde {F.mes(a['ventana3'][0])}.",
            "Priorizar estos clientes en la planeación de visitas.", sum(max(0, x["exceso"]) for x in sp),
            hipotesis=a.get("texto_prevencion"), enlace={"vista": "sin_prevencion"},
            corto=f"{n_crit} crítico{'s' if n_crit != 1 else ''} y {len(sp) - n_crit} moderado{'s' if len(sp) - n_crit != 1 else ''} sin actividades desde {F.mes(a['ventana3'][0])}"))
    for hz in a["calidad_critica"]:
        alertas.append(Alerta("alta", "Calidad de datos", hz["descripcion"], f"{F.num(hz['registros'])} registros. {hz['tratamiento']}",
                              "Revisar el reporte de calidad antes de tomar decisiones con los indicadores afectados.", 0, grupo=0,
                              enlace={"vista": "calidad"}))
    # Orden: primero lo general, luego situaciones puntuales por casos en exceso, al final las tendencias.
    alertas.sort(key=lambda x: (x.grupo, -x.impacto, ORDEN_NIVEL[x.nivel]))
    return alertas
