"""
Construye el proyecto Power BI (PBIP) del tablero de siniestralidad:

    seccion_1_powerbi/Siniestralidad_Clientes.pbip
    seccion_1_powerbi/Siniestralidad_Clientes.SemanticModel/   (modelo en TMDL)
    seccion_1_powerbi/Siniestralidad_Clientes.Report/          (reporte en PBIR)

El formato PBIP es el formato "fuente" de Power BI Desktop (texto versionable en Git).
Se abre con doble clic en el .pbip y se puede guardar como .pbix desde Archivo > Guardar como.

Uso:
    python datos/generar_datos.py                  # 1. datos de origen (CSV)
    python seccion_1_powerbi/construir_pbip.py     # 2. proyecto Power BI
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import modelo_semantico as ms            # noqa: E402
import recursos_graficos as rg           # noqa: E402

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
NOMBRE = "Siniestralidad_Clientes"
DATOS = RAIZ / "datos" / "salida"
PBIX_REFERENCIA = RAIZ / "N022_Excelencia_Operacional 21-09.pbix"

SCH = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VC = f"{SCH}/visualContainer/2.12.0/schema.json"
MED = "_Medidas"

AZUL, CIAN, TINTA, TINTA2, GRIS = "#0055A0", "#00ABC4", "#16212E", "#4A5666", "#6B7684"
FUENTE = "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif"
FUENTE_SB = "'Segoe UI Semibold', wf_segoe-ui_semibold, helvetica, arial, sans-serif"


# ===========================================================================
# Utilidades PBIR
# ===========================================================================
def L(v):
    """Literal PBIR: str -> 'texto', bool -> true/false, int -> 12L, float -> 12D."""
    if isinstance(v, bool):
        val = "true" if v else "false"
    elif isinstance(v, int):
        val = f"{v}L"
    elif isinstance(v, float):
        val = f"{v:g}D"
    else:
        val = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": val}}}


def D(v):
    """Literal decimal (D) para tamaños/posiciones."""
    return {"expr": {"Literal": {"Value": f"{v:g}D"}}}


def color(hex_):
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{hex_}'"}}}}}


def col(ent, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}


def mea(prop, ent=MED):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}


def color_medida(prop):
    return {"solid": {"color": {"expr": mea(prop)}}}


def proy(campo, nombre=None, activo=False):
    if "Measure" in campo:
        ent, prop = campo["Measure"]["Expression"]["SourceRef"]["Entity"], campo["Measure"]["Property"]
    else:
        ent, prop = campo["Column"]["Expression"]["SourceRef"]["Entity"], campo["Column"]["Property"]
    p = {"field": campo, "queryRef": f"{ent}.{prop}", "nativeQueryRef": nombre or prop}
    if nombre:
        p["displayName"] = nombre
    if activo:
        p["active"] = True
    return p


def props(**kw):
    return [{"properties": kw}]


class Pagina:
    def __init__(self, nombre, titulo, fondo=None, oculta=False):
        self.nombre, self.titulo, self.fondo, self.oculta = nombre, titulo, fondo, oculta
        self.visuales: list[dict] = []
        self.z = 1000

    def add(self, nombre, x, y, w, h, visual=None, tipo=None, contenedor=None, grupo=None):
        self.z += 100
        v = {"$schema": VC, "name": f"{self.nombre[:3]}_{nombre}"[:50],
             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z}}
        if visual is not None:
            v["visual"] = visual
        v.update(contenedor or {})
        self.visuales.append(v)
        return v

    def json(self):
        p = {"$schema": f"{SCH}/page/2.1.0/schema.json", "name": self.nombre, "displayName": self.titulo,
             "displayOption": "FitToPage", "height": 720, "width": 1280}
        if self.oculta:
            p["visibility"] = "HiddenInViewMode"
        if self.fondo:
            p["objects"] = {
                "background": [{"properties": {
                    "image": {"image": {"name": L(self.fondo), "url": {"expr": {"ResourcePackageItem": {
                        "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": self.fondo}}},
                        "scaling": L("Fit")}},
                    "transparency": D(0)}}],
                "outspace": [{"properties": {"color": color("#E9ECF1")}}],
            }
        return p


# ---------------------------------------------------------------------------
# Estilo de contenedor (tarjeta blanca redondeada, título centrado en azul SURA)
# ---------------------------------------------------------------------------
def vco(titulo=None, fondo=True, borde=True, tam_titulo=12, titulo_medida=None, padding=None, alineacion="left",
        subtitulo_medida=None):
    o = {
        "background": props(show=L(fondo), color=color("#FFFFFF"), transparency=D(0)),
        "border": props(show=L(borde), color=color("#DFE4EA"), radius=D(10)),
        "dropShadow": props(show=L(False)),
        "visualHeader": props(show=L(False)),
    }
    if titulo or titulo_medida:
        t = dict(show=L(True), fontColor=color(AZUL), bold=L(True), fontSize=D(tam_titulo),
                 alignment=L(alineacion), fontFamily=L(FUENTE_SB), titleWrap=L(True))
        t["text"] = {"expr": mea(titulo_medida)} if titulo_medida else L(titulo)
        o["title"] = props(**t)
    else:
        o["title"] = props(show=L(False))
    if subtitulo_medida:
        o["subTitle"] = props(show=L(True), text={"expr": mea(subtitulo_medida)}, fontColor=color(TINTA2),
                              fontSize=D(9), alignment=L(alineacion), titleWrap=L(True))
    if padding is not None:
        o["padding"] = props(top=D(padding), bottom=D(padding), left=D(padding), right=D(padding))
    return o


# ===========================================================================
# Constructores de visuales
# ===========================================================================
def textbox(parrafos, fondo=False, borde=False):
    """parrafos: lista de listas de (texto, estilo) o de str."""
    pars = []
    for p in parrafos:
        alin = "left"
        if isinstance(p, dict):
            alin, p = p.get("align", "left"), p["runs"]
        runs = []
        for r in (p if isinstance(p, list) else [p]):
            if isinstance(r, str):
                r = (r, {})
            texto, est = r
            est = {"fontFamily": "Segoe UI", "fontSize": "10pt", "color": TINTA, **est}
            runs.append({"value": texto, "textStyle": est})
        pars.append({"textRuns": runs, "horizontalTextAlignment": alin})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": pars}}]},
            "visualContainerObjects": {**vco(fondo=fondo, borde=borde), "padding": props(top=D(4), bottom=D(4), left=D(8), right=D(8))},
            "drillFilterOtherVisuals": True}


def titulo_pagina(pg: Pagina, titulo, subtitulo):
    pg.add("titulo", 160, 6, 424, 42, textbox([{"runs": [(titulo, {"fontWeight": "bold", "fontSize": "18pt", "color": AZUL})]}]))
    pg.add("subtitulo", 160, 42, 424, 30, textbox([{"runs": [(subtitulo, {"fontFamily": "Segoe UI Light", "fontSize": "11pt", "color": TINTA2})]}]))


def slicer(ent, prop, encabezado, grupo, modo="Dropdown", orden_desc=False, unico=False):
    q = {"queryState": {"Values": {"projections": [proy(col(ent, prop), activo=True)]}}}
    if orden_desc:
        q["sortDefinition"] = {"sort": [{"field": col(ent, prop), "direction": "Descending"}]}
    return {
        "visualType": "slicer", "query": q,
        "objects": {
            "data": props(mode=L(modo)),
            "selection": props(singleSelect=L(unico), selectAllCheckboxEnabled=L(not unico)),
            "header": props(show=L(True), text=L(encabezado), fontFamily=L(FUENTE_SB), textSize=D(10),
                            fontColor=color(AZUL), outlineStyle=D(0)),
            "items": props(textSize=D(10), outlineStyle=D(0), fontColor=color(TINTA)),
            "general": props(selfFilterEnabled=L(True)),
        },
        "visualContainerObjects": {**vco(fondo=False, borde=False), "padding": props(top=D(2), bottom=D(2), left=D(4), right=D(4))},
        "syncGroup": {"groupName": grupo, "fieldChanges": True, "filterChanges": True},
        "drillFilterOtherVisuals": True,
    }


def boton_nav(destino=None, tooltip="", tipo="PageNavigation"):
    link = dict(show=L(True), type=L(tipo), tooltip=L(tooltip))
    if destino:
        link["navigationSection"] = L(destino)
    return {
        "visualType": "actionButton",
        "objects": {"icon": [{"properties": {"shapeType": L("blank")}, "selector": {"id": "default"}},
                             {"properties": {"show": L(False)}}],
                    "outline": props(show=L(False)),
                    "text": props(show=L(False)),
                    "fill": [{"properties": {"show": L(False)}}]},
        "visualContainerObjects": {"visualLink": props(**link), "title": props(show=L(False), text=L(tooltip)),
                                   "background": props(show=L(False))},
        "drillFilterOtherVisuals": True,
    }


def card(medida, tam=20, color_txt=TINTA, color_med=None, negrita=True, titulo=None, alinear_izq=False, fondo=True, borde=True):
    labels = dict(fontSize=D(tam), bold=L(negrita), fontFamily=L(FUENTE_SB if negrita else FUENTE),
                  labelDisplayUnits=D(1))
    labels["color"] = color_medida(color_med) if color_med else color(color_txt)
    return {
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [proy(mea(medida))]}}},
        "objects": {"labels": props(**labels), "categoryLabels": props(show=L(False)),
                    "wordWrap": props(show=L(True))},
        "visualContainerObjects": {**vco(titulo, fondo=fondo, borde=borde, tam_titulo=10),
                                   "padding": props(top=D(2), bottom=D(2), left=D(8), right=D(8))},
        "drillFilterOtherVisuals": True,
    }


def kpi(pg: Pagina, clave, x, y, w, titulo, medida, var_texto=None, var_color=None, h=88):
    """Tarjeta KPI: título + valor grande + variación coloreada (rojo empeora / verde mejora)."""
    v = card(medida, tam=22, titulo=titulo)
    v["visualContainerObjects"]["title"] = props(show=L(True), text=L(titulo), fontColor=color(TINTA2), bold=L(True),
                                                  fontSize=D(10), alignment=L("left"), fontFamily=L(FUENTE_SB))
    v["visualContainerObjects"]["padding"] = props(top=D(0), bottom=D(22), left=D(10), right=D(10))
    pg.add(f"kpi_{clave}", x, y, w, h, v)
    if var_texto:
        pg.add(f"kpiv_{clave}", x + 4, y + h - 26, w - 8, 22,
               card(var_texto, tam=9, color_med=var_color, negrita=True, fondo=False, borde=False))


def ref_line(medida, etiqueta, color_linea=GRIS):
    return [{"properties": {"show": L(True), "displayName": L(etiqueta), "value": {"expr": mea(medida)},
                            "lineColor": color(color_linea), "transparency": D(0), "style": L("dashed"),
                            "width": D(2), "dataLabelShow": L(False), "dataLabelColor": color(TINTA2),
                            "dataLabelDecimalPoints": D(1), "dataLabelHorizontalPosition": L("right"),
                            "dataLabelVerticalPosition": L("above"), "dataLabelDisplayUnits": D(1),
                            "dataLabelText": L("ValueAndName")},
             "selector": {"id": "1"}}]


def eje_comun(ejes_ocultos=False):
    return {
        "categoryAxis": props(fontSize=D(9), labelColor=color(TINTA2), showAxisTitle=L(False), gridlineShow=L(False)),
        "valueAxis": props(show=L(not ejes_ocultos), fontSize=D(9), labelColor=color(GRIS), showAxisTitle=L(False),
                           gridlineShow=L(True), gridlineColor=color("#E6E9EE"), gridlineStyle=L("solid")),
        "legend": props(show=L(False)),
    }


def grafico(tipo, categoria, medidas, titulo=None, titulo_medida=None, colores=None, color_fx=None,
            referencia=None, etiquetas=True, leyenda=False, orden=None, formato_etiqueta=None, series=None,
            subtitulo_medida=None):
    """Gráfico genérico (columnas, barras, líneas) con estilo homogéneo."""
    qs = {"Category": {"projections": [proy(categoria, activo=True)]},
          "Y": {"projections": [proy(mea(m), n) for m, n in medidas]}}
    if series is not None:
        qs["Series"] = {"projections": [proy(series)]}
    q = {"queryState": qs}
    if orden:
        q["sortDefinition"] = {"sort": [{"field": orden[0], "direction": orden[1]}], "isDefaultSort": False}
    obj = eje_comun()
    obj["legend"] = props(show=L(leyenda), position=L("Top"), fontSize=D(9), labelColor=color(TINTA2))
    obj["labels"] = props(show=L(etiquetas), fontSize=D(9), color=color(TINTA), enableBackground=L(False),
                          **({"labelDisplayUnits": D(1)} if formato_etiqueta is None else {}))
    dp = []
    if colores:
        for (m, _), c in zip(medidas, colores):
            dp.append({"properties": {"fill": color(c)}, "selector": {"metadata": f"{MED}.{m}"}})
    if color_fx:
        dp.append({"properties": {"fill": color_medida(color_fx)},
                   "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}})
    if dp:
        obj["dataPoint"] = dp
    if tipo == "lineChart":
        obj["lineStyles"] = props(showMarker=L(True), markerSize=D(4), strokeWidth=D(2))
    if referencia:
        obj["y1AxisReferenceLine"] = ref_line(*referencia)
    return {"visualType": tipo, "query": q, "objects": obj,
            "visualContainerObjects": vco(titulo, titulo_medida=titulo_medida, subtitulo_medida=subtitulo_medida),
            "drillFilterOtherVisuals": True}


def tabla(columnas, titulo, orden=None, colores_fx=None, matriz=False, filas=None, tam=9, totales=True):
    """Tabla (tableEx) o matriz (pivotTable). columnas: lista de (campo, nombre)."""
    if matriz:
        qs = {"Rows": {"projections": [proy(c, n, activo=(i == 0)) for i, (c, n) in enumerate(filas)]},
              "Values": {"projections": [proy(c, n) for c, n in columnas]}}
        tipo = "pivotTable"
    else:
        qs = {"Values": {"projections": [proy(c, n) for c, n in columnas]}}
        tipo = "tableEx"
    q = {"queryState": qs}
    if orden:
        q["sortDefinition"] = {"sort": [{"field": orden[0], "direction": orden[1]}]}
    obj = {
        "columnHeaders": props(fontSize=D(tam), bold=L(True), fontColor=color(AZUL), backColor=color("#EEF3F9"),
                               alignment=L("Center"), wordWrap=L(True)),
        "values": [{"properties": {"fontSize": D(tam), "fontColorPrimary": color(TINTA),
                                   "fontColorSecondary": color(TINTA), "backColorPrimary": color("#FFFFFF"),
                                   "backColorSecondary": color("#F7F9FC")}}],
        "grid": props(outlineColor=color("#E7E7E7"), gridVertical=L(False), gridHorizontal=L(True),
                      gridHorizontalColor=color("#E7E7E7"), gridHorizontalWeight=D(1), rowPadding=D(3)),
        "total": props(totals=L(totales), fontSize=D(tam), bold=L(True), fontColor=color(AZUL), backColor=color("#EEF3F9")),
    }
    if matriz:
        obj["rowHeaders"] = props(fontSize=D(tam), fontColor=color(TINTA), fontFamily=L(FUENTE_SB))
        obj["subTotals"] = props(rowSubtotals=L(True))
        obj["general"] = props(layout=L("Outline"))
    for meta, fx in (colores_fx or {}).items():
        obj["values"].append({"properties": {"fontColor": color_medida(fx)},
                              "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": meta}})
    return {"visualType": tipo, "query": q, "objects": obj, "visualContainerObjects": vco(titulo),
            "drillFilterOtherVisuals": True}


def navegador_inicio(paginas_visibles: list[str], todas: list[str]):
    pages = [{"properties": {"showHiddenPages": L(True)}}]
    for p in todas:
        pages.append({"properties": {"showPage": L(p in paginas_visibles)}, "selector": {"id": p}})
    return {
        "visualType": "pageNavigator",
        "objects": {
            "pages": pages,
            "layout": props(orientation=D(1), cellPadding=D(20)),
            "text": [{"properties": {"show": L(True)}},
                     {"properties": {"fontColor": color(AZUL), "fontSize": D(14), "fontFamily": L(FUENTE_SB),
                                     "horizontalAlignment": L("left"), "leftMargin": D(16), "bold": L(True)},
                      "selector": {"id": "default"}},
                     {"properties": {"fontColor": color("#FFFFFF")}, "selector": {"id": "hover"}}],
            "fill": [{"properties": {"show": L(True)}},
                     {"properties": {"fillColor": color("#FFFFFF"), "transparency": D(0)}, "selector": {"id": "default"}},
                     {"properties": {"fillColor": color(AZUL), "transparency": D(0)}, "selector": {"id": "hover"}}],
            "outline": [{"properties": {"show": L(True)}},
                        {"properties": {"lineColor": color("#DFE4EA"), "weight": D(1)}, "selector": {"id": "default"}}],
            "shape": [{"properties": {"tileShape": L("rectangleRounded"), "roundEdge": D(10)}, "selector": {"id": "default"}}],
        },
        "visualContainerObjects": {"background": props(show=L(False)), "border": props(show=L(False)),
                                   "title": props(show=L(False)), "visualHeader": props(show=L(False))},
        "drillFilterOtherVisuals": True,
    }


# ===========================================================================
# Páginas
# ===========================================================================
P_INI, P_RES, P_SIN, P_CLI, P_FIL, P_INF = ("p0_inicio", "p1_resumen", "p2_siniestralidad",
                                            "p3_clientes", "p4_filtros", "p5_informacion")
ORDEN = [P_INI, P_RES, P_SIN, P_CLI, P_FIL, P_INF]


def encabezado_comun(pg: Pagina, titulo, subtitulo, anterior, siguiente):
    """Encabezado idéntico en todas las páginas de análisis (patrón de la referencia)."""
    titulo_pagina(pg, titulo, subtitulo)
    # filtros globales sincronizados entre páginas
    pg.add("s_coord", 590, 12, 150, 56, slicer("Clientes", "Coordinador", "Coordinador", "Coordinador"))
    pg.add("s_sector", 744, 12, 150, 56, slicer("Clientes", "Sector", "Sector", "Sector"))
    pg.add("s_anio", 898, 12, 90, 56, slicer("Calendario", "Año", "Año", "Anio", orden_desc=True))
    pg.add("s_periodo", 992, 12, 136, 56, slicer("Calendario", "Periodo", "Periodo", "Periodo", orden_desc=True))
    # navegación: logo e icono casa -> inicio; flechas -> página anterior / siguiente
    pg.add("b_logo", 12, 10, 140, 60, boton_nav(P_INI, "Ir al inicio"))
    pg.add("b_inicio", 1146, 18, 44, 44, boton_nav(P_INI, "Inicio"))
    if anterior:
        pg.add("b_atras", 1190, 18, 44, 44, boton_nav(anterior, "Página anterior"))
    if siguiente:
        pg.add("b_adelante", 1232, 18, 44, 44, boton_nav(siguiente, "Página siguiente"))
    # franja de filtros: texto de filtros aplicados + mes de análisis + más filtros + borrar filtros
    v = card("Filtros aplicados", tam=9, color_txt=TINTA2, negrita=False, fondo=False, borde=False)
    v["objects"]["labels"] = props(fontSize=D(9), color=color(TINTA2), fontFamily=L(FUENTE))
    pg.add("filtros", 14, 84, 560, 30, v)
    v = card("Texto mes de análisis", tam=9, color_txt=AZUL, negrita=True, fondo=False, borde=False)
    pg.add("mes_analisis", 14, 112, 560, 30, v)
    pg.add("b_mas_filtros", 1178, 88, 46, 46, boton_nav(P_FIL, "Más filtros"))
    pg.add("b_borrar", 1224, 88, 46, 46, boton_nav(None, "Borrar todos los filtros", tipo="ClearAllSlicers"))


def pagina_inicio() -> Pagina:
    pg = Pagina(P_INI, "Inicio", fondo="fondo_inicio.jpg")
    pg.add("titulo", 36, 118, 470, 90, textbox([
        [("Siniestralidad y prevención", {"fontWeight": "bold", "fontSize": "24pt", "color": AZUL})],
        [("Clientes empresariales · tablero de control ejecutivo", {"fontFamily": "Segoe UI Light", "fontSize": "13pt", "color": TINTA2})],
    ]))
    pg.add("linea", 44, 214, 380, 8, {"visualType": "shape", "objects": {
        "shape": props(tileShape=L("line")), "rotation": props(shapeAngle=D(0)),
        "fill": [{"properties": {"fillColor": color(CIAN)}, "selector": {"id": "default"}}],
        "outline": [{"properties": {"lineColor": color(CIAN), "weight": D(3)}, "selector": {"id": "default"}}]},
        "drillFilterOtherVisuals": True})
    pg.add("guia", 36, 226, 440, 40, textbox([[("Elija una sección para comenzar:", {"fontSize": "11pt", "color": TINTA2})]]))
    pg.add("nav", 96, 276, 360, 252, navegador_inicio([P_RES, P_SIN, P_CLI, P_INF], ORDEN))
    pg.add("t_fecha", 96, 588, 380, 30, textbox([{"align": "center", "runs": [("Fecha de corte de los datos", {"fontWeight": "bold", "fontSize": "11pt", "color": AZUL})]}]))
    v = card("Texto actualización", tam=10, color_txt=TINTA2, negrita=False, fondo=False, borde=False)
    pg.add("fecha", 96, 616, 380, 30, v)
    return pg


def pagina_resumen() -> Pagina:
    pg = Pagina(P_RES, "Resumen ejecutivo", fondo="fondo_p1.jpg")
    encabezado_comun(pg, "Resumen ejecutivo", "¿Cómo va la siniestralidad este mes?", None, P_SIN)
    pg.add("s_clase", 590, 86, 290, 56, slicer("Clientes", "Clase de riesgo", "Clase de riesgo", "Clase"))
    pg.add("s_estado", 884, 86, 290, 56, slicer("Clientes", "Estado cliente", "Estado del cliente", "EstadoCliente"))
    # KPIs del mes de análisis
    y, w, gap, x0 = 154, 205, 7.6, 6
    kp = [("casos", "Casos del mes", "Casos mes", "Texto var casos", "Color var casos"),
          ("costo", "Costo del mes", "Costo mes", "Texto var costo", "Color var costo"),
          ("tasa", "Tasa de incidencia (x 100 trab.)", "Tasa mes", "Texto var tasa", "Color var tasa"),
          ("graves", "% casos graves", "% graves mes", "Texto var % graves", "Color var % graves"),
          ("criticos", "Clientes críticos (tasa > 5)", "Clientes críticos", "Texto var críticos", "Color var críticos"),
          ("prev", "Prevención (últimos 30 días)", "Actividades prevención 30 días", None, None)]
    for i, (k, t, m, vt, vc_) in enumerate(kp):
        kpi(pg, k, x0 + i * (w + gap), y, w, t, m, vt, vc_)
    pg.add("kpiv_prev", x0 + 5 * (w + gap) + 4, y + 88 - 26, w - 8, 22,
           card("Texto sin prevención", tam=9, color_med="Color sin prevención", negrita=True, fondo=False, borde=False))
    # Tendencia (eje desconectado de 12 meses) con promedio histórico
    ejes = col("Eje Periodo", "Mes eje")
    pg.add("tendencia", 6, 250, 628, 228, grafico(
        "clusteredColumnChart", ejes, [("Casos tendencia", "Casos")], titulo_medida="Título tendencia",
        color_fx="Color barra tendencia", referencia=("Promedio histórico casos", "Promedio histórico"),
        orden=(ejes, "Ascending"), subtitulo_medida="Subtítulo tendencia casos"))
    pg.add("tasa", 640, 250, 634, 228, grafico(
        "lineChart", ejes, [("Tasa tendencia", "Tasa de incidencia")],
        titulo_medida="Título tasa", colores=[AZUL],
        referencia=("Promedio histórico tasa", "Promedio histórico"), orden=(ejes, "Ascending"),
        subtitulo_medida="Subtítulo tendencia tasa"))
    # Distribuciones y clientes a atender
    pg.add("clase", 6, 484, 408, 230, grafico(
        "clusteredColumnChart", col("Clientes", "Clase de riesgo"), [("Casos mes", "Casos del mes")],
        titulo="Casos del mes por clase de riesgo", colores=[AZUL], orden=(col("Clientes", "Clase de riesgo"), "Ascending")))
    pg.add("tipo", 420, 484, 408, 230, grafico(
        "clusteredBarChart", col("Casos", "Tipo de caso"),
        [("% participación casos por tipo", "% de los casos"), ("% participación costo", "% del costo")],
        titulo="Leves vs graves: participación en casos y en costo", colores=[AZUL, "#EB6834"], leyenda=True,
        formato_etiqueta="pct"))
    pg.add("top", 834, 484, 440, 230, tabla(
        [(col("Clientes", "Cliente"), "Cliente"), (col("Clientes", "Clase de riesgo"), "Clase"),
         (mea("Casos mes"), "Casos"), (mea("Tasa mes"), "Tasa"), (mea("Clasificación"), "Estado")],
        "Clientes con mayor tasa del mes", orden=(mea("Tasa mes"), "Descending"),
        colores_fx={f"{MED}.Clasificación": "Color clasificación"}, totales=False))
    return pg


def pagina_siniestralidad() -> Pagina:
    pg = Pagina(P_SIN, "Siniestralidad", fondo="fondo_p2.jpg")
    encabezado_comun(pg, "Detalle de siniestralidad", "¿Dónde se concentran los casos y el costo?", P_RES, P_CLI)
    pg.add("s_tipo", 590, 86, 190, 56, slicer("Casos", "Tipo de caso", "Tipo de caso", "TipoCaso"))
    pg.add("s_estcaso", 784, 86, 190, 56, slicer("Casos", "Estado del caso", "Estado del caso", "EstadoCaso"))
    pg.add("s_clase", 978, 86, 196, 56, slicer("Clientes", "Clase de riesgo", "Clase de riesgo", "Clase"))
    y, w, gap = 154, 250, 4.5
    kp = [("ytd", "Casos acumulados del año (YTD)", "Casos YTD"), ("costo", "Costo acumulado del año", "Costo YTD"),
          ("dias", "Días de ausencia (periodo filtrado)", "Días de ausencia"),
          ("prom", "Costo promedio por caso", "Costo promedio por caso"),
          ("abiertos", "Casos graves abiertos (12 meses)", "Graves abiertos a la fecha")]
    for i, (k, t, m) in enumerate(kp):
        kpi(pg, k, 6 + i * (w + gap), y, w, t, m, h=70)
    pg.add("matriz", 6, 230, 760, 484, tabla(
        [(mea("Total casos"), "Casos"), (mea("% participación casos"), "% del total"),
         (mea("Casos graves"), "Graves"), (mea("% casos graves"), "% graves"),
         (mea("Días de ausencia"), "Días ausencia"), (mea("Costo total"), "Costo"),
         (mea("Tasa de incidencia"), "Tasa")],
        "Casos por sector y cliente (periodo filtrado · expanda el sector para ver clientes)", matriz=True,
        filas=[(col("Clientes", "Sector"), "Sector"), (col("Clientes", "Cliente"), "Cliente")],
        orden=(mea("Total casos"), "Descending"), tam=10))
    pg.add("sector", 772, 230, 502, 262, grafico(
        "clusteredBarChart", col("Clientes", "Sector"), [("Tasa de incidencia", "Tasa de incidencia")],
        titulo="Tasa de incidencia por sector (periodo filtrado)", colores=[AZUL],
        orden=(mea("Tasa de incidencia"), "Descending")))
    ejes = col("Eje Periodo", "Mes eje")
    pg.add("tipo_mes", 772, 498, 502, 216, grafico(
        "columnChart", ejes, [("Casos leves tendencia", "Leves"), ("Casos graves tendencia", "Graves")],
        titulo="Casos leves y graves · 12 meses hasta el mes de análisis", colores=[AZUL, "#EB6834"], leyenda=True,
        orden=(ejes, "Ascending"), etiquetas=False))
    return pg


def pagina_clientes() -> Pagina:
    pg = Pagina(P_CLI, "Clientes y prevención", fondo="fondo_p3.jpg")
    encabezado_comun(pg, "Clientes y prevención", "¿A quién visitar primero y qué hacer?", P_SIN, None)
    pg.add("s_clase", 590, 86, 290, 56, slicer("Clientes", "Clase de riesgo", "Clase de riesgo", "Clase"))
    pg.add("s_regional", 884, 86, 290, 56, slicer("Clientes", "Regional", "Regional", "Regional"))
    y, w, gap = 154, 250, 4.5
    kp = [("activos", "Clientes con facturación en el mes", "Clientes con facturación"),
          ("crit", "Clientes críticos (tasa > 5)", "Clientes críticos"),
          ("mod", "Clientes moderados (tasa 2 a 5)", "Clientes moderados"),
          ("sinprev", "Clientes sin prevención en 30 días", "Clientes sin prevención 30 días"),
          ("act", "Actividades de prevención (30 días)", "Actividades prevención 30 días")]
    for i, (k, t, m) in enumerate(kp):
        kpi(pg, k, 6 + i * (w + gap), y, w, t, m, h=70)
    pg.add("prioridad", 6, 230, 760, 484, tabla(
        [(col("Clientes", "Cliente"), "Cliente"), (col("Clientes", "Coordinador"), "Coordinador"),
         (col("Clientes", "Clase de riesgo"), "Clase"), (mea("Casos 90 días"), "Casos 90 d"),
         (mea("Tasa 90 días"), "Tasa 90 d"), (mea("Graves abiertos a la fecha"), "Graves abiertos"),
         (mea("Días sin prevención"), "Días sin prev."), (mea("Clasificación"), "Estado mes")],
        "Clientes a priorizar: mayor tasa de los últimos 90 días primero", orden=(mea("Tasa 90 días"), "Descending"),
        colores_fx={f"{MED}.Clasificación": "Color clasificación"}, totales=False, tam=8.5))
    disp = {"visualType": "scatterChart", "query": {"queryState": {
        "Category": {"projections": [proy(col("Clientes", "Cliente"), activo=True)]},
        "X": {"projections": [proy(mea("Actividades por 100 trabajadores 12m"), "Prevención (act. x 100 trab., 12 m)")]},
        "Y": {"projections": [proy(mea("Tasa 90 días"), "Tasa 90 días")]},
        "Size": {"projections": [proy(mea("Trabajadores activos"), "Trabajadores")]}}},
        "objects": {**eje_comun(), "dataPoint": props(defaultColor=color(AZUL), fillTransparency=D(35)),
                    "categoryAxis": props(fontSize=D(9), labelColor=color(TINTA2), showAxisTitle=L(True),
                                          titleText=L("Actividades de prevención por 100 trabajadores (12 meses)"), titleFontSize=D(9)),
                    "valueAxis": props(fontSize=D(9), labelColor=color(GRIS), showAxisTitle=L(True),
                                       titleText=L("Tasa 90 días"), titleFontSize=D(9), gridlineColor=color("#E6E9EE"))},
        "visualContainerObjects": vco("¿Más prevención, menos casos? (cada punto es un cliente)"),
        "drillFilterOtherVisuals": True}
    pg.add("dispersion", 772, 230, 502, 250, disp)
    pg.add("tipo_prev", 772, 486, 502, 228, grafico(
        "clusteredBarChart", col("Prevencion", "Tipo de actividad"), [("Actividades prevención", "Actividades")],
        titulo="Actividades de prevención por tipo (periodo filtrado)", colores=[CIAN],
        orden=(mea("Actividades prevención"), "Descending")))
    return pg


def pagina_filtros() -> Pagina:
    pg = Pagina(P_FIL, "Panel de filtros", fondo="fondo_panel.jpg", oculta=True)
    titulo_pagina(pg, "Panel de filtros", "Las selecciones aplican a todas las páginas")
    pg.add("b_logo", 12, 10, 140, 60, boton_nav(P_INI, "Ir al inicio"))
    pg.add("b_volver", 1206, 16, 56, 50, boton_nav(None, "Volver a la página anterior", tipo="Back"))
    v = card("Filtros aplicados", tam=10, color_txt=TINTA2, negrita=False, fondo=False, borde=False)
    pg.add("filtros", 20, 90, 1240, 34, v)
    campos = [("Calendario", "Año", "Año", "Anio"), ("Calendario", "Periodo", "Periodo", "Periodo"),
              ("Clientes", "Coordinador", "Coordinador", "Coordinador"), ("Clientes", "Regional", "Regional", "Regional"),
              ("Clientes", "Sector", "Sector", "Sector"), ("Clientes", "Clase de riesgo", "Clase de riesgo", "Clase"),
              ("Clientes", "Estado cliente", "Estado del cliente", "EstadoCliente"),
              ("Casos", "Tipo de caso", "Tipo de caso", "TipoCaso"), ("Casos", "Estado del caso", "Estado del caso", "EstadoCaso"),
              ("Clientes", "Cliente", "Cliente", "Cliente")]
    for i, (e, p, enc, g) in enumerate(campos):
        fila, colm = divmod(i, 5)
        s = slicer(e, p, enc, g, modo="Basic", orden_desc=(p in ("Año", "Periodo")))
        s["visualContainerObjects"] = vco(fondo=True, borde=True)
        pg.add(f"s{i}", 20 + colm * 250, 132 + fila * 290, 238, 276, s)
    return pg


def pagina_info() -> Pagina:
    pg = Pagina(P_INF, "Información del reporte", fondo="fondo_panel.jpg", oculta=True)
    titulo_pagina(pg, "Información del reporte", "Definiciones, fuentes y notas de uso")
    pg.add("b_logo", 12, 10, 140, 60, boton_nav(P_INI, "Ir al inicio"))
    pg.add("b_volver", 1206, 16, 56, 50, boton_nav(None, "Volver a la página anterior", tipo="Back"))
    h = {"fontWeight": "bold", "color": AZUL, "fontSize": "11pt"}
    b = {"fontWeight": "bold"}
    pg.add("defs", 18, 92, 610, 612, textbox([
        [("Definiciones oficiales (viven una sola vez en el modelo semántico)", h)],
        [("Caso: ", b), "incidente registrado con estado Abierto o Cerrado. Los Anulados no cuentan."],
        [("Tasa de incidencia: ", b), "casos del mes ÷ trabajadores activos del mes × 100. Para varios meses se usa casos ÷ trabajadores-mes × 100 (tasa mensual promedio). Los trabajadores activos salen de facturación."],
        [("Clasificación del cliente: ", b), "Crítico si la tasa del mes es mayor a 5; Moderado entre 2 y 5; Bajo menor a 2 (misma regla del pipeline SQL diario)."],
        [("Mes de análisis: ", b), "el último mes incluido en los filtros. Si es el mes en curso, se compara contra los mismos días del mes anterior para no castigar un mes incompleto."],
        [("Variaciones: ", b), "▲ rojo = empeora (sube), ▼ verde = mejora (baja). 'Sin dato del mes anterior' cuando no existe historia para comparar."],
        [("Casos graves: ", b), "según el campo oficial tipo = grave (no por días de ausencia)."],
        [("Prevención 30 días: ", b), "actividades realizadas entre la fecha de corte − 29 días y la fecha de corte."],
        [" "],
        [("Fuente y actualización", h)],
        ["Tablas clientes, casos, facturación y prevención (datos sintéticos generados por datos/generar_datos.py). Actualización diaria; los datos llegan con corte al día anterior."],
        [" "],
        [("Seguridad por perfil (RLS)", h)],
        ["Rol Coordinador: cada persona ve solo los clientes que tiene asignados según su correo (tabla Seguridad Asignacion). Rol Gerencia: todos los clientes."],
        [" "],
        [("Cómo usar", h)],
        ["Filtros globales arriba a la derecha; filtros de la página en la franja gris; ícono de embudo + para más filtros y embudo × para borrarlos. Pase el cursor sobre cualquier gráfico para ver el detalle."],
    ], fondo=False))
    pg.add("t15", 640, 88, 624, 32, textbox([[("Pregunta 1.5 — medidas A, B y C (el primer mes de la historia no tiene mes anterior)", h)]]))
    t = tabla([(col("Calendario", "Periodo"), "Periodo"), (mea("Total casos"), "Casos válidos"),
               (mea("A · Casos YTD (literal)"), "A literal (incluye anulados)"), (mea("Casos YTD"), "A sobre casos válidos"),
               (mea("C · Var vs mes anterior (literal)"), "C literal"), (mea("C · Var vs mes anterior (corregida)"), "C corregida")],
              None, orden=(col("Calendario", "Periodo"), "Ascending"), totales=False)
    pg.add("t_abc", 640, 120, 624, 300, t)
    pg.add("t_b", 640, 426, 624, 280, tabla(
        [(col("Clientes", "Sector"), "Sector"), (mea("Total casos"), "Casos"),
         (mea("% participación casos"), "B con ALL(clientes)"), (mea("B · % participación sin ALL"), "B sin ALL (siempre 100 %)")],
        "Medida B: ALL(clientes) es lo que permite obtener el % sobre el total", orden=(mea("Total casos"), "Descending")))
    return pg


# ===========================================================================
# Ensamblado
# ===========================================================================
def tema() -> dict:
    return {
        "name": "Tema SURA siniestralidad",
        "dataColors": [AZUL, CIAN, "#EB6834", "#1C5CAB", "#86B6EF", "#6B7684", "#0CA30C", "#D99A00", "#104281", "#9EC5F4"],
        "background": "#FFFFFF", "foreground": TINTA, "tableAccent": AZUL,
        "good": "#0CA30C", "neutral": "#D99A00", "bad": "#D03B3B",
        "maximum": "#104281", "center": "#86B6EF", "minimum": "#EEF3F9",
        "textClasses": {
            "callout": {"fontFace": FUENTE_SB, "color": TINTA},
            "title": {"fontFace": FUENTE_SB, "color": AZUL, "fontSize": 12},
            "header": {"fontFace": FUENTE_SB, "color": AZUL},
            "label": {"fontFace": FUENTE, "color": TINTA2},
        },
        "visualStyles": {"*": {"*": {
            "border": [{"show": True, "color": {"solid": {"color": "#DFE4EA"}}, "radius": 10}],
            "dropShadow": [{"show": False}],
        }}},
    }


def escribir_json(ruta: Path, data):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def construir_reporte(carpeta: Path, recursos: dict[str, str], tmp_recursos: Path):
    defi = carpeta / "definition"
    escribir_json(carpeta / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NOMBRE}.SemanticModel"}}})
    escribir_json(defi / "version.json", {"$schema": f"{SCH}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    # recursos: tema base (del reporte de referencia), tema personalizado, fondos
    rr = carpeta / "StaticResources" / "RegisteredResources"
    rr.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(PBIX_REFERENCIA) as z:
        base = carpeta / "StaticResources" / "SharedResources" / "BaseThemes" / "CY23SU04.json"
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_bytes(z.read("Report/StaticResources/SharedResources/BaseThemes/CY23SU04.json"))
    escribir_json(rr / "TemaSURA.json", tema())
    items = [{"name": "TemaSURA.json", "path": "TemaSURA.json", "type": "CustomTheme"}]
    for nombre in recursos.values():
        shutil.copy(tmp_recursos / nombre, rr / nombre)
        items.append({"name": nombre, "path": nombre, "type": "Image"})
    escribir_json(defi / "report.json", {
        "$schema": f"{SCH}/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY23SU04", "reportVersionAtImport": {"visual": "1.8.80", "report": "2.0.80", "page": "1.3.80"}, "type": "SharedResources"},
            "customTheme": {"name": "TemaSURA.json", "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"}, "type": "RegisteredResources"}},
        "objects": {"section": [{"properties": {"verticalAlignment": L("Top")}}],
                    "outspacePane": [{"properties": {"expanded": L(False)}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources", "items": [{"name": "CY23SU04", "path": "BaseThemes/CY23SU04.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources", "items": items}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    })
    paginas = [pagina_inicio(), pagina_resumen(), pagina_siniestralidad(), pagina_clientes(), pagina_filtros(), pagina_info()]
    escribir_json(defi / "pages" / "pages.json", {"$schema": f"{SCH}/pagesMetadata/1.1.0/schema.json",
                                                  "pageOrder": ORDEN, "activePageName": P_INI})
    for pg in paginas:
        escribir_json(defi / "pages" / pg.nombre / "page.json", pg.json())
        nombres = set()
        for v in pg.visuales:
            assert v["name"] not in nombres, v["name"]
            nombres.add(v["name"])
            escribir_json(defi / "pages" / pg.nombre / "visuals" / v["name"] / "visual.json", v)
    return paginas


def construir_modelo(carpeta: Path):
    escribir_json(carpeta / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    d = carpeta / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (d / "roles").mkdir(parents=True, exist_ok=True)
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1601\n", encoding="utf-8")
    tablas = ms.tablas()
    tablas["_Medidas"] = ms.medidas_tmdl()
    for nombre, contenido in tablas.items():
        (d / "tables" / f"{nombre}.tmdl").write_text(contenido, encoding="utf-8")
    (d / "model.tmdl").write_text(ms.modelo_tmdl(list(tablas)), encoding="utf-8")
    (d / "relationships.tmdl").write_text(ms.relaciones_tmdl(), encoding="utf-8")
    ruta = str(DATOS.resolve()) + "\\"
    (d / "expressions.tmdl").write_text(ms.expresiones_tmdl(ruta), encoding="utf-8")
    for nombre, contenido in ms.roles_tmdl().items():
        (d / "roles" / f"{nombre}.tmdl").write_text(contenido, encoding="utf-8")


def borrar(ruta: Path, intentos: int = 10):
    """Borra un archivo o carpeta tolerando bloqueos breves (OneDrive, antivirus, Desktop cerrando)."""
    import os
    import stat
    import time

    def quitar_solo_lectura(func, path, _):
        # OneDrive marca carpetas como solo lectura; Windows no permite borrarlas así
        os.chmod(path, stat.S_IWRITE)
        func(path)

    for i in range(intentos):
        try:
            if ruta.is_dir():
                shutil.rmtree(ruta, onerror=quitar_solo_lectura)
            else:
                os.chmod(ruta, stat.S_IWRITE)
                ruta.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if i == intentos - 1:
                raise SystemExit(f"No se pudo borrar {ruta}: ciérrelo en Power BI Desktop y reintente.")
            time.sleep(1.5)


def main():
    if not (DATOS / "casos.csv").exists():
        sys.exit("Primero genere los datos: python datos/generar_datos.py")
    if not PBIX_REFERENCIA.exists():
        sys.exit(f"No se encontró el reporte de referencia (iconos y tema base): {PBIX_REFERENCIA}")
    rep, sm = AQUI / f"{NOMBRE}.Report", AQUI / f"{NOMBRE}.SemanticModel"
    for c in (rep, sm):
        if c.exists():
            # se conserva la caché local de Desktop (.pbi) si existe
            for hijo in c.iterdir():
                if hijo.name != ".pbi":
                    borrar(hijo)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        iconos = tmp / "iconos_ref"
        iconos.mkdir()
        with zipfile.ZipFile(PBIX_REFERENCIA) as z:
            for n in z.namelist():
                if n.startswith("Report/StaticResources/RegisteredResources/") and n.endswith(".png"):
                    (iconos / Path(n).name).write_bytes(z.read(n))
        recursos = rg.generar(tmp / "recursos", RAIZ, iconos)
        construir_modelo(sm)
        paginas = construir_reporte(rep, recursos, tmp / "recursos")
    escribir_json(AQUI / f"{NOMBRE}.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}], "settings": {"enableAutoRecovery": True}})
    (AQUI / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    total = sum(len(p.visuales) for p in paginas)
    print(f"Proyecto generado: {AQUI / (NOMBRE + '.pbip')}  ({len(paginas)} páginas, {total} visuales, "
          f"{len(ms.MEDIDAS)} medidas)")


if __name__ == "__main__":
    main()
