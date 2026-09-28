"""
Definición del modelo semántico (TMDL) del tablero de siniestralidad.

Modelo estrella:
    Hechos      : Casos, Facturacion, Prevencion
    Dimensiones : Clientes (incluye coordinador asignado), Calendario
    Soporte     : Eje Periodo (eje desconectado para tendencias de 12 meses),
                  Info Actualizacion (fecha de corte), Seguridad Asignacion (RLS),
                  _Medidas (todas las medidas, organizadas por carpetas).

La definición OFICIAL de cada indicador vive una sola vez aquí (capa compartida):
todas las páginas y cualquier reporte conectado a este modelo usan las mismas medidas.
"""
from __future__ import annotations

import uuid
from textwrap import dedent, indent

NS = uuid.UUID("7d3c1c7e-5b0e-4c55-9f2a-2b1c0a9e5d11")


def tag(nombre: str) -> str:
    """lineageTag determinístico (estable entre ejecuciones del generador)."""
    return str(uuid.uuid5(NS, nombre))


def q(nombre: str) -> str:
    """Cita un nombre TMDL si tiene espacios o caracteres especiales."""
    return nombre if nombre.replace("_", "").isalnum() else "'" + nombre.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Columnas: (nombre, tipo, formato, oculta, extra)
# ---------------------------------------------------------------------------
def valor_tmdl(v: str) -> str:
    """Valor de propiedad TMDL: si trae comillas se encierra entre comillas y se duplican."""
    return '"' + v.replace('"', '""') + '"' if '"' in v else v


def columna(tabla, nombre, tipo, fmt=None, oculta=False, resumir="none", sort_by=None, key=False,
            categoria=None, descripcion=None, carpeta=None):
    lineas = []
    if descripcion:
        lineas.append(f"\t/// {descripcion}")
    lineas.append(f"\tcolumn {q(nombre)}")
    lineas.append(f"\t\tdataType: {tipo}")
    if fmt:
        lineas.append(f"\t\tformatString: {valor_tmdl(fmt)}")
    if key:
        lineas.append("\t\tisKey")
    if oculta:
        lineas.append("\t\tisHidden")
    if categoria:
        lineas.append(f"\t\tdataCategory: {categoria}")
    if carpeta:
        lineas.append(f"\t\tdisplayFolder: {carpeta}")
    lineas.append(f"\t\tlineageTag: {tag(tabla + '.' + nombre)}")
    lineas.append(f"\t\tsummarizeBy: {resumir}")
    lineas.append(f"\t\tsourceColumn: {nombre}")
    if sort_by:
        lineas.append(f"\t\tsortByColumn: {q(sort_by)}")
    if tipo == "dateTime":
        lineas.append("")
        lineas.append("\t\tannotation UnderlyingDateTimeDataType = Date")
    return "\n".join(lineas) + "\n"


def particion_m(tabla: str, m: str) -> str:
    cuerpo = indent(dedent(m).strip("\n"), "\t\t\t\t")
    return f"\tpartition {q(tabla)} = m\n\t\tmode: import\n\t\tsource =\n{cuerpo}\n"


def tabla_tmdl(nombre, columnas, m, oculta=False, categoria=None, descripcion=None):
    cab = []
    if descripcion:
        cab.append(f"/// {descripcion}")
    cab.append(f"table {q(nombre)}")
    if oculta:
        cab.append("\tisHidden")
    if categoria:
        cab.append(f"\tdataCategory: {categoria}")
    cab.append(f"\tlineageTag: {tag(nombre)}")
    return "\n".join(cab) + "\n\n" + "\n".join(columnas) + "\n" + particion_m(nombre, m) + "\n"


CSV = 'Csv.Document(File.Contents(RutaDatos & "{archivo}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv])'


def m_csv(archivo, tipos, renombrar, extra=""):
    """Plantilla M: lee CSV UTF-8, promueve encabezados, tipa con cultura en-US y renombra."""
    tipos_m = ", ".join(f'{{"{c}", {t}}}' for c, t in tipos)
    ren_m = ", ".join(f'{{"{a}", "{b}"}}' for a, b in renombrar)
    return f"""
        let
            Origen = {CSV.format(archivo=archivo)},
            Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),
            // Cultura en-US: el CSV usa punto decimal y fechas ISO
            Tipos = Table.TransformColumnTypes(Encabezados, {{{tipos_m}}}, "en-US"),{extra}
            Renombradas = Table.RenameColumns(Paso, {{{ren_m}}})
        in
            Renombradas
    """


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------
def tablas() -> dict[str, str]:
    t = {}

    t["Clientes"] = tabla_tmdl("Clientes", [
        columna("Clientes", "id_cliente", "int64", "0", oculta=True, key=True),
        columna("Clientes", "Cliente", "string", descripcion="Razón social del cliente empresarial."),
        columna("Clientes", "Sector", "string"),
        columna("Clientes", "Clase riesgo num", "int64", "0", oculta=True),
        columna("Clientes", "Clase de riesgo", "string", sort_by="Clase riesgo num",
                descripcion="Clase de riesgo del cliente (1 = menor riesgo, 5 = mayor riesgo)."),
        columna("Clientes", "Estado cliente", "string"),
        columna("Clientes", "Fecha de vinculación", "dateTime", "dd/mm/yyyy"),
        columna("Clientes", "Coordinador", "string", descripcion="Coordinador de cuenta asignado actualmente."),
        columna("Clientes", "Regional", "string"),
        columna("Clientes", "Correo coordinador", "string", oculta=True),
    ], m_csv("clientes.csv",
             [("id_cliente", "Int64.Type"), ("nombre", "type text"), ("sector", "type text"),
              ("clase_riesgo", "Int64.Type"), ("estado", "type text"), ("fecha_vinculacion", "type date")],
             [("nombre", "Cliente"), ("sector", "Sector"), ("clase_riesgo", "Clase riesgo num"),
              ("fecha_vinculacion", "Fecha de vinculación")],
             extra="""
            Clase = Table.AddColumn(Tipos, "Clase de riesgo", each "Clase " & Text.From([clase_riesgo]), type text),
            Estado = Table.AddColumn(Clase, "Estado cliente", each Text.Proper([estado]), type text),
            SinEstado = Table.RemoveColumns(Estado, {"estado"}),
            // Coordinador vigente (asignación) + atributos del coordinador
            Asignacion = Table.TransformColumnTypes(Table.PromoteHeaders(""" + CSV.format(archivo="asignacion_coordinador.csv") + """, [PromoteAllScalars = true]), {{"id_cliente", Int64.Type}, {"id_coordinador", Int64.Type}}, "en-US"),
            Coordinadores = Table.TransformColumnTypes(Table.PromoteHeaders(""" + CSV.format(archivo="coordinadores.csv") + """, [PromoteAllScalars = true]), {{"id_coordinador", Int64.Type}}, "en-US"),
            ConAsignacion = Table.NestedJoin(SinEstado, {"id_cliente"}, Asignacion, {"id_cliente"}, "A", JoinKind.LeftOuter),
            ExpA = Table.ExpandTableColumn(ConAsignacion, "A", {"id_coordinador"}, {"id_coordinador"}),
            ConCoord = Table.NestedJoin(ExpA, {"id_coordinador"}, Coordinadores, {"id_coordinador"}, "C", JoinKind.LeftOuter),
            ExpC = Table.ExpandTableColumn(ConCoord, "C", {"nombre_coordinador", "regional", "correo"}, {"Coordinador", "Regional", "Correo coordinador"}),
            Paso = Table.RemoveColumns(ExpC, {"id_coordinador"}),"""),
        descripcion="Dimensión de clientes empresariales con su coordinador de cuenta vigente.")

    t["Casos"] = tabla_tmdl("Casos", [
        columna("Casos", "ID caso", "int64", "0", oculta=True),
        columna("Casos", "id_cliente", "int64", "0", oculta=True),
        columna("Casos", "id_trabajador", "int64", "0", oculta=True),
        columna("Casos", "Fecha ocurrencia", "dateTime", "dd/mm/yyyy"),
        columna("Casos", "Tipo de caso", "string", descripcion="Leve o Grave, según el campo oficial casos.tipo."),
        columna("Casos", "Días de ausencia", "int64", "#,0", oculta=True),
        columna("Casos", "Costo", "double", "\\$ #,0", oculta=True),
        columna("Casos", "Estado del caso", "string", descripcion="Abierto, Cerrado o Anulado. Los anulados no cuentan como casos."),
    ], m_csv("casos.csv",
             [("id_caso", "Int64.Type"), ("id_cliente", "Int64.Type"), ("id_trabajador", "Int64.Type"),
              ("fecha_ocurrencia", "type date"), ("tipo", "type text"), ("dias_ausencia", "Int64.Type"),
              ("costo", "type number"), ("estado", "type text")],
             [("id_caso", "ID caso"), ("fecha_ocurrencia", "Fecha ocurrencia"), ("dias_ausencia", "Días de ausencia"),
              ("costo", "Costo")],
             extra="""
            Tipo = Table.TransformColumns(Tipos, {{"tipo", Text.Proper, type text}, {"estado", Text.Proper, type text}}),
            Paso = Table.RenameColumns(Tipo, {{"tipo", "Tipo de caso"}, {"estado", "Estado del caso"}}),"""),
        descripcion="Hecho: un registro por incidente reportado.")

    t["Facturacion"] = tabla_tmdl("Facturacion", [
        columna("Facturacion", "id_cliente", "int64", "0", oculta=True),
        columna("Facturacion", "Periodo", "dateTime", "mmm yyyy", oculta=True),
        columna("Facturacion", "Trabajadores activos", "int64", "#,0", oculta=True),
        columna("Facturacion", "Valor contrato", "double", "\\$ #,0", oculta=True),
    ], m_csv("facturacion.csv",
             [("id_cliente", "Int64.Type"), ("periodo", "type date"), ("trabajadores_activos", "Int64.Type"),
              ("valor_contrato", "type number")],
             [("periodo", "Periodo"), ("trabajadores_activos", "Trabajadores activos"), ("valor_contrato", "Valor contrato")],
             extra="\n            Paso = Tipos,"),
        descripcion="Hecho: un registro por cliente y periodo facturado (día 1 del mes). Fuente de trabajadores activos.")

    t["Prevencion"] = tabla_tmdl("Prevencion", [
        columna("Prevencion", "ID actividad", "int64", "0", oculta=True),
        columna("Prevencion", "id_cliente", "int64", "0", oculta=True),
        columna("Prevencion", "Fecha actividad", "dateTime", "dd/mm/yyyy"),
        columna("Prevencion", "Tipo de actividad", "string"),
        columna("Prevencion", "Participantes", "int64", "#,0", oculta=True),
    ], m_csv("prevencion.csv",
             [("id_actividad", "Int64.Type"), ("id_cliente", "Int64.Type"), ("fecha", "type date"),
              ("tipo", "type text"), ("participantes", "Int64.Type")],
             [("id_actividad", "ID actividad"), ("fecha", "Fecha actividad"), ("tipo", "Tipo de actividad"),
              ("participantes", "Participantes")],
             extra="\n            Paso = Tipos,"),
        descripcion="Hecho: actividades de prevención realizadas con cada cliente.")

    m_cal = """
        let
            Corte = Date.From(Text.Trim(Text.FromBinary(File.Contents(RutaDatos & "fecha_corte.txt")))),
            Inicio = #date(Date.Year(Corte) - 2, 1, 1),
            Fin = Date.EndOfMonth(Corte),
            Lista = List.Dates(Inicio, Duration.Days(Fin - Inicio) + 1, #duration(1, 0, 0, 0)),
            Tabla = Table.FromList(Lista, Splitter.SplitByNothing(), {"Fecha"}),
            TipoFecha = Table.TransformColumnTypes(Tabla, {{"Fecha", type date}}),
            Meses = {"Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"},
            Anio = Table.AddColumn(TipoFecha, "Año", each Date.Year([Fecha]), Int64.Type),
            MesNum = Table.AddColumn(Anio, "Mes número", each Date.Month([Fecha]), Int64.Type),
            Mes = Table.AddColumn(MesNum, "Mes", each Meses{[Mes número] - 1}, type text),
            Periodo = Table.AddColumn(Mes, "Periodo", each [Mes] & " " & Text.From([Año]), type text),
            Orden = Table.AddColumn(Periodo, "Periodo orden", each [Año] * 100 + [Mes número], Int64.Type),
            InicioMes = Table.AddColumn(Orden, "Inicio mes", each Date.StartOfMonth([Fecha]), type date),
            Trimestre = Table.AddColumn(InicioMes, "Trimestre", each "T" & Text.From(Date.QuarterOfYear([Fecha])), type text),
            EstadoMes = Table.AddColumn(Trimestre, "Estado del mes", each if [Inicio mes] = Date.StartOfMonth(Corte) then "En curso" else "Cerrado", type text)
        in
            EstadoMes
    """
    t["Calendario"] = tabla_tmdl("Calendario", [
        columna("Calendario", "Fecha", "dateTime", "dd/mm/yyyy", key=True),
        columna("Calendario", "Año", "int64", "0"),
        columna("Calendario", "Mes número", "int64", "0", oculta=True),
        columna("Calendario", "Mes", "string", sort_by="Mes número"),
        columna("Calendario", "Periodo", "string", sort_by="Periodo orden",
                descripcion="Mes y año, por ejemplo 'Sep 2026'."),
        columna("Calendario", "Periodo orden", "int64", "0", oculta=True),
        columna("Calendario", "Inicio mes", "dateTime", "dd/mm/yyyy", oculta=True),
        columna("Calendario", "Trimestre", "string"),
        columna("Calendario", "Estado del mes", "string", descripcion="'En curso' para el mes de la fecha de corte; 'Cerrado' para los demás."),
    ], m_cal, categoria="Time", descripcion="Calendario diario desde el 1 de enero de dos años antes de la fecha de corte hasta el fin del mes del corte.")

    m_eje = """
        let
            Corte = Date.From(Text.Trim(Text.FromBinary(File.Contents(RutaDatos & "fecha_corte.txt")))),
            Meses = {"Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"},
            Numero = List.Numbers(0, 24 + Date.Month(Corte)),
            Inicios = List.Transform(Numero, each Date.AddMonths(#date(Date.Year(Corte) - 2, 1, 1), _)),
            Tabla = Table.FromList(Inicios, Splitter.SplitByNothing(), {"Inicio mes"}),
            Tipo = Table.TransformColumnTypes(Tabla, {{"Inicio mes", type date}}),
            Etiqueta = Table.AddColumn(Tipo, "Mes eje", each Meses{Date.Month([Inicio mes]) - 1} & " " & Text.End(Text.From(Date.Year([Inicio mes])), 2), type text),
            Orden = Table.AddColumn(Etiqueta, "Orden", each Date.Year([Inicio mes]) * 100 + Date.Month([Inicio mes]), Int64.Type)
        in
            Orden
    """
    t["Eje Periodo"] = tabla_tmdl("Eje Periodo", [
        columna("Eje Periodo", "Inicio mes", "dateTime", "dd/mm/yyyy", oculta=True),
        columna("Eje Periodo", "Mes eje", "string", sort_by="Orden"),
        columna("Eje Periodo", "Orden", "int64", "0", oculta=True),
    ], m_eje, descripcion="Eje desconectado de meses: permite mostrar siempre los 12 meses que terminan en el mes de análisis, aunque el usuario filtre un periodo.")

    m_info = """
        let
            Corte = Date.From(Text.Trim(Text.FromBinary(File.Contents(RutaDatos & "fecha_corte.txt")))),
            Tabla = #table(type table [#"Fecha corte" = date, #"Fecha actualización" = datetime], {{Corte, DateTime.LocalNow()}})
        in
            Tabla
    """
    t["Info Actualizacion"] = tabla_tmdl("Info Actualizacion", [
        columna("Info Actualizacion", "Fecha corte", "dateTime", "dd/mm/yyyy"),
        columna("Info Actualizacion", "Fecha actualización", "dateTime", "dd/mm/yyyy hh:nn"),
    ], m_info, oculta=True, descripcion="Fecha de corte de los datos y momento de la última actualización del modelo.")

    t["Seguridad Asignacion"] = tabla_tmdl("Seguridad Asignacion", [
        columna("Seguridad Asignacion", "id_cliente", "int64", "0"),
        columna("Seguridad Asignacion", "Correo", "string"),
    ], """
        let
            Origen = """ + CSV.format(archivo="asignacion_coordinador.csv") + """,
            Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),
            Tipos = Table.TransformColumnTypes(Encabezados, {{"id_cliente", Int64.Type}, {"correo", type text}}, "en-US"),
            Seleccion = Table.SelectColumns(Tipos, {"id_cliente", "correo"}),
            Minus = Table.TransformColumns(Seleccion, {{"correo", Text.Lower, type text}}),
            Renombradas = Table.RenameColumns(Minus, {{"correo", "Correo"}})
        in
            Renombradas
    """, oculta=True, descripcion="Tabla de seguridad (RLS): qué clientes ve cada correo. Se alimenta de la asignación vigente de coordinadores.")
    return t


# ---------------------------------------------------------------------------
# Medidas
# ---------------------------------------------------------------------------
# (nombre, carpeta, formato, descripción, expresión DAX)
MEDIDAS: list[tuple[str, str, str, str, str]] = [
    # ---- 0. Fechas y contexto
    ("Fecha corte", "0. Contexto", "dd/mm/yyyy", "Último día con datos (corte del día anterior a la carga).",
     "MAX ( 'Info Actualizacion'[Fecha corte] )"),
    ("Mes de análisis", "0. Contexto", "dd/mm/yyyy",
     "Primer día del mes que se analiza: el último mes dentro de los filtros, sin pasar del mes de la fecha de corte.",
     """
     VAR _corte = [Fecha corte]
     VAR _mesCorte = DATE ( YEAR ( _corte ), MONTH ( _corte ), 1 )
     VAR _mes = MAX ( Calendario[Inicio mes] )
     RETURN IF ( ISBLANK ( _mes ), BLANK (), MIN ( _mes, _mesCorte ) )"""),
    ("Fin mes de análisis", "0. Contexto", "dd/mm/yyyy", "Último día evaluado del mes de análisis (fin de mes o fecha de corte).",
     "MIN ( EOMONTH ( [Mes de análisis], 0 ), [Fecha corte] )"),
    ("Es mes en curso", "0. Contexto", "\"Sí\";\"Sí\";\"No\"", "1 si el mes de análisis es el mes de la fecha de corte (datos parciales).",
     "INT ( EOMONTH ( [Mes de análisis], 0 ) > [Fecha corte] )"),
    ("Texto mes de análisis", "0. Contexto", "", "Etiqueta del mes analizado y contra qué se compara.",
     """
     VAR _mes = [Mes de análisis]
     VAR _ant = EDATE ( _mes, -1 )
     VAR _etq = LOOKUPVALUE ( Calendario[Periodo], Calendario[Fecha], _mes )
     VAR _etqAnt = LOOKUPVALUE ( Calendario[Periodo], Calendario[Fecha], _ant )
     RETURN
         IF (
             ISBLANK ( _mes ), "Sin periodo en los filtros",
             IF (
                 [Es mes en curso] = 1,
                 "Mes de análisis: " & _etq & " (en curso, datos al " & FORMAT ( [Fecha corte], "dd/mm/yyyy", "es-CO" )
                     & ") · se compara con el 1-" & DAY ( [Fecha corte] ) & " de " & _etqAnt,
                 "Mes de análisis: " & _etq & " (cerrado) · se compara con " & _etqAnt
             )
         )"""),
    ("Texto actualización", "0. Contexto", "", "Texto de fecha de corte y actualización para la portada.",
     "\"Corte: \" & FORMAT ( [Fecha corte], \"dd/mm/yyyy\", \"es-CO\" ) & \"  ·  Actualizado: \" & FORMAT ( MAX ( 'Info Actualizacion'[Fecha actualización] ), \"dd/mm/yyyy hh:nn\", \"es-CO\" )"),
    ("Filtros aplicados", "0. Contexto", "", "Resumen legible de los filtros activos (se muestra bajo el encabezado).",
     """
     VAR _lista = {
         IF ( ISFILTERED ( Clientes[Coordinador] ), "Coordinador: " & CONCATENATEX ( VALUES ( Clientes[Coordinador] ), Clientes[Coordinador], ", " ) ),
         IF ( ISFILTERED ( Clientes[Regional] ), "Regional: " & CONCATENATEX ( VALUES ( Clientes[Regional] ), Clientes[Regional], ", " ) ),
         IF ( ISFILTERED ( Clientes[Sector] ), "Sector: " & CONCATENATEX ( VALUES ( Clientes[Sector] ), Clientes[Sector], ", " ) ),
         IF ( ISFILTERED ( Clientes[Clase de riesgo] ), "Clase: " & CONCATENATEX ( VALUES ( Clientes[Clase de riesgo] ), Clientes[Clase de riesgo], ", " ) ),
         IF ( ISFILTERED ( Clientes[Estado cliente] ), "Estado cliente: " & CONCATENATEX ( VALUES ( Clientes[Estado cliente] ), Clientes[Estado cliente], ", " ) ),
         IF ( ISFILTERED ( Clientes[Cliente] ), "Cliente: " & IF ( COUNTROWS ( VALUES ( Clientes[Cliente] ) ) > 2, COUNTROWS ( VALUES ( Clientes[Cliente] ) ) & " seleccionados", CONCATENATEX ( VALUES ( Clientes[Cliente] ), Clientes[Cliente], ", " ) ) ),
         IF ( ISFILTERED ( Calendario[Año] ), "Año: " & CONCATENATEX ( VALUES ( Calendario[Año] ), Calendario[Año], ", " ) ),
         IF ( ISFILTERED ( Calendario[Periodo] ), "Periodo: " & CONCATENATEX ( VALUES ( Calendario[Periodo] ), Calendario[Periodo], ", ", CALCULATE ( MIN ( Calendario[Periodo orden] ) ), ASC ) ),
         IF ( ISFILTERED ( Casos[Tipo de caso] ), "Tipo de caso: " & CONCATENATEX ( VALUES ( Casos[Tipo de caso] ), Casos[Tipo de caso], ", " ) ),
         IF ( ISFILTERED ( Casos[Estado del caso] ), "Estado del caso: " & CONCATENATEX ( VALUES ( Casos[Estado del caso] ), Casos[Estado del caso], ", " ) )
     }
     VAR _txt = CONCATENATEX ( FILTER ( _lista, [Value] <> BLANK () ), [Value], "   |   " )
     RETURN IF ( _txt = "", "Sin filtros aplicados: vista de todos los clientes", "Filtros aplicados → " & _txt )"""),

    # ---- 1. Casos (definiciones base, fuente única)
    ("Total casos", "1. Casos", "#,0", "Casos válidos (se excluyen los anulados) en el contexto de filtros.",
     "CALCULATE ( COUNTROWS ( Casos ), KEEPFILTERS ( Casos[Estado del caso] <> \"Anulado\" ) )"),
    ("Casos graves", "1. Casos", "#,0", "Casos válidos de tipo Grave.",
     "CALCULATE ( [Total casos], KEEPFILTERS ( Casos[Tipo de caso] = \"Grave\" ) )"),
    ("Casos leves", "1. Casos", "#,0", "Casos válidos de tipo Leve.",
     "CALCULATE ( [Total casos], KEEPFILTERS ( Casos[Tipo de caso] = \"Leve\" ) )"),
    ("% casos graves", "1. Casos", "0.0 %", "Participación de los casos graves en el total de casos.",
     "DIVIDE ( [Casos graves], [Total casos] )"),
    ("Casos abiertos", "1. Casos", "#,0", "Casos válidos que siguen abiertos.",
     "CALCULATE ( [Total casos], KEEPFILTERS ( Casos[Estado del caso] = \"Abierto\" ) )"),
    ("Casos graves abiertos", "1. Casos", "#,0", "Casos graves que siguen abiertos (requieren seguimiento).",
     "CALCULATE ( [Casos graves], KEEPFILTERS ( Casos[Estado del caso] = \"Abierto\" ) )"),
    ("Días de ausencia", "1. Casos", "#,0", "Suma de días de ausencia de los casos válidos.",
     "CALCULATE ( SUM ( Casos[Días de ausencia] ), KEEPFILTERS ( Casos[Estado del caso] <> \"Anulado\" ) )"),
    ("Costo total", "1. Casos", "\\$ #,0,,.0 \"M\"", "Costo de los casos válidos, en millones de pesos.",
     "CALCULATE ( SUM ( Casos[Costo] ), KEEPFILTERS ( Casos[Estado del caso] <> \"Anulado\" ) )"),
    ("Costo promedio por caso", "1. Casos", "\\$ #,0,,.0 \"M\"", "Costo total / casos.",
     "DIVIDE ( [Costo total], [Total casos] )"),
    ("% costo casos graves", "1. Casos", "0.0 %", "Participación de los casos graves en el costo total.",
     "DIVIDE ( CALCULATE ( [Costo total], KEEPFILTERS ( Casos[Tipo de caso] = \"Grave\" ) ), [Costo total] )"),
    ("% participación casos", "1. Casos", "0.0 %",
     "Participación de la fila en los casos de todos los clientes (Medida B de la prueba, sobre [Total casos]).",
     "DIVIDE ( [Total casos], CALCULATE ( [Total casos], ALL ( Clientes ) ), 0 )"),
    ("% participación costo", "1. Casos", "0.0 %", "Participación de la fila en el costo de todos los tipos de caso.",
     "DIVIDE ( [Costo total], CALCULATE ( [Costo total], ALL ( Casos[Tipo de caso] ) ) )"),
    ("% participación casos por tipo", "1. Casos", "0.0 %", "Participación de la fila en los casos de todos los tipos.",
     "DIVIDE ( [Total casos], CALCULATE ( [Total casos], ALL ( Casos[Tipo de caso] ) ) )"),
    ("Casos YTD", "1. Casos", "#,0", "Casos acumulados desde el 1 de enero hasta la fecha del contexto (Medida A, sobre casos válidos).",
     "TOTALYTD ( [Total casos], Calendario[Fecha] )"),
    ("Costo YTD", "1. Casos", "\\$ #,0,,.0 \"M\"", "Costo acumulado del año.",
     "TOTALYTD ( [Costo total], Calendario[Fecha] )"),

    # ---- 2. Exposición
    ("Trabajadores-mes", "2. Exposición", "#,0",
     "Suma de trabajadores activos facturados en los meses del contexto (denominador oficial de la tasa).",
     "SUM ( Facturacion[Trabajadores activos] )"),
    ("Trabajadores activos", "2. Exposición", "#,0",
     "Trabajadores activos del mes de análisis (facturación del periodo).",
     "VAR _m = [Mes de análisis] RETURN CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), Calendario[Fecha] = _m )"),
    ("Clientes con facturación", "2. Exposición", "#,0", "Clientes facturados en el mes de análisis.",
     "VAR _m = [Mes de análisis] RETURN CALCULATE ( DISTINCTCOUNT ( Facturacion[id_cliente] ), REMOVEFILTERS ( Calendario ), Calendario[Fecha] = _m )"),

    # ---- 3. Tasa de incidencia (definición oficial)
    ("Tasa de incidencia", "3. Tasa de incidencia", "#,0.00",
     "DEFINICIÓN OFICIAL: casos / trabajadores activos × 100, por mes. Para varios meses = casos / trabajadores-mes × 100 (tasa mensual promedio ponderada).",
     "DIVIDE ( [Total casos], [Trabajadores-mes] ) * 100"),

    # ---- 4. Mes de análisis vs mes anterior
    ("Casos mes", "4. Mes de análisis", "#,0", "Casos del mes de análisis (hasta la fecha de corte si está en curso).",
     "CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Mes de análisis], [Fin mes de análisis] ) )"),
    ("Casos mes anterior", "4. Mes de análisis", "#,0",
     "Casos del mes anterior en un periodo comparable: completo si el mes de análisis está cerrado; mismos días transcurridos si está en curso.",
     """
     VAR _ini = [Mes de análisis]
     VAR _dias = DAY ( [Fin mes de análisis] )
     VAR _iniAnt = EDATE ( _ini, -1 )
     VAR _finAnt = MIN ( EOMONTH ( _iniAnt, 0 ), _iniAnt + _dias - 1 )
     VAR _hayHistoria = _iniAnt >= MINX ( ALL ( Calendario[Fecha] ), Calendario[Fecha] )
     RETURN
         IF ( _hayHistoria,
             CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _iniAnt, _finAnt ) ) + 0
         )"""),
    ("Var casos", "4. Mes de análisis", "+#,0;-#,0;0", "Diferencia de casos vs el mes anterior comparable. En blanco si no hay mes anterior.",
     "IF ( NOT ISBLANK ( [Casos mes anterior] ), [Casos mes] - [Casos mes anterior] )"),
    ("Var % casos", "4. Mes de análisis", "+0.0 %;-0.0 %;0.0 %", "Variación porcentual de casos vs el mes anterior comparable.",
     "DIVIDE ( [Var casos], [Casos mes anterior] )"),
    ("Costo mes", "4. Mes de análisis", "\\$ #,0,,.0 \"M\"", "Costo de los casos del mes de análisis.",
     "CALCULATE ( [Costo total], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Mes de análisis], [Fin mes de análisis] ) )"),
    ("Costo mes anterior", "4. Mes de análisis", "\\$ #,0,,.0 \"M\"", "Costo del mes anterior comparable.",
     """
     VAR _ini = [Mes de análisis]
     VAR _dias = DAY ( [Fin mes de análisis] )
     VAR _iniAnt = EDATE ( _ini, -1 )
     VAR _finAnt = MIN ( EOMONTH ( _iniAnt, 0 ), _iniAnt + _dias - 1 )
     RETURN
         IF ( _iniAnt >= MINX ( ALL ( Calendario[Fecha] ), Calendario[Fecha] ),
             CALCULATE ( [Costo total], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _iniAnt, _finAnt ) ) + 0
         )"""),
    ("Var % costo", "4. Mes de análisis", "+0.0 %;-0.0 %;0.0 %", "Variación porcentual del costo vs el mes anterior comparable.",
     "DIVIDE ( [Costo mes] - [Costo mes anterior], [Costo mes anterior] )"),
    ("Tasa mes", "4. Mes de análisis", "#,0.00", "Tasa de incidencia del mes de análisis: casos del mes / trabajadores activos del mes × 100.",
     "DIVIDE ( [Casos mes], [Trabajadores activos] ) * 100"),
    ("Tasa mes anterior", "4. Mes de análisis", "#,0.00", "Tasa del mes anterior comparable (mismos días si el mes de análisis está en curso).",
     """
     VAR _ant = EDATE ( [Mes de análisis], -1 )
     VAR _trabAnt = CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), Calendario[Fecha] = _ant )
     RETURN DIVIDE ( [Casos mes anterior], _trabAnt ) * 100"""),
    ("Var tasa", "4. Mes de análisis", "+#,0.00;-#,0.00;0.00", "Diferencia de la tasa en puntos vs el mes anterior comparable.",
     "IF ( NOT ISBLANK ( [Tasa mes anterior] ), [Tasa mes] - [Tasa mes anterior] )"),
    ("Casos graves mes", "4. Mes de análisis", "#,0", "Casos graves del mes de análisis.",
     "CALCULATE ( [Casos graves], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Mes de análisis], [Fin mes de análisis] ) )"),
    ("% graves mes", "4. Mes de análisis", "0.0 %", "Participación de casos graves en el mes de análisis.",
     "DIVIDE ( [Casos graves mes], [Casos mes] )"),
    ("% graves mes anterior", "4. Mes de análisis", "0.0 %", "Participación de graves en el mes anterior comparable.",
     """
     VAR _ini = [Mes de análisis]
     VAR _dias = DAY ( [Fin mes de análisis] )
     VAR _iniAnt = EDATE ( _ini, -1 )
     VAR _finAnt = MIN ( EOMONTH ( _iniAnt, 0 ), _iniAnt + _dias - 1 )
     RETURN
         CALCULATE ( [% casos graves], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _iniAnt, _finAnt ) )"""),

    # ---- 5. Textos y colores de variación (para tarjetas)
    ("Texto var casos", "5. Tarjetas", "", "Variación de casos lista para mostrar.",
     """
     VAR _v = [Var casos]
     RETURN IF ( ISBLANK ( _v ), "Sin dato del mes anterior",
         IF ( _v > 0, "▲ ", IF ( _v < 0, "▼ ", "= " ) ) & FORMAT ( ABS ( _v ), "#,0", "es-CO" ) & " ("
             & FORMAT ( ABS ( [Var % casos] ), "0.0 %", "es-CO" ) & ") vs mes ant." )"""),
    ("Texto var costo", "5. Tarjetas", "", "Variación de costo lista para mostrar.",
     """
     VAR _v = [Var % costo]
     RETURN IF ( ISBLANK ( _v ), "Sin dato del mes anterior",
         IF ( _v > 0, "▲ ", IF ( _v < 0, "▼ ", "= " ) ) & FORMAT ( ABS ( _v ), "0.0 %", "es-CO" ) & " vs mes ant." )"""),
    ("Texto var tasa", "5. Tarjetas", "", "Variación de la tasa (puntos) lista para mostrar.",
     """
     VAR _v = [Var tasa]
     RETURN IF ( ISBLANK ( _v ), "Sin dato del mes anterior",
         IF ( _v > 0, "▲ ", IF ( _v < 0, "▼ ", "= " ) ) & FORMAT ( ABS ( _v ), "#,0.00", "es-CO" ) & " pts vs mes ant." )"""),
    ("Texto var % graves", "5. Tarjetas", "", "Variación de la participación de graves (puntos porcentuales).",
     """
     VAR _v = [% graves mes] - [% graves mes anterior]
     RETURN IF ( ISBLANK ( [% graves mes anterior] ), "Sin dato del mes anterior",
         IF ( _v > 0, "▲ ", IF ( _v < 0, "▼ ", "= " ) ) & FORMAT ( ABS ( _v ) * 100, "0.0", "es-CO" ) & " p.p. vs mes ant." )"""),
    ("Color var casos", "5. Tarjetas", "", "Rojo si empeora (sube), verde si mejora (baja), gris si igual o sin dato.",
     "SWITCH ( TRUE (), ISBLANK ( [Var casos] ), \"#6B7684\", [Var casos] > 0, \"#B42F2F\", [Var casos] < 0, \"#0A7D0A\", \"#6B7684\" )"),
    ("Color var costo", "5. Tarjetas", "", "Rojo si el costo sube, verde si baja.",
     "SWITCH ( TRUE (), ISBLANK ( [Var % costo] ), \"#6B7684\", [Var % costo] > 0, \"#B42F2F\", [Var % costo] < 0, \"#0A7D0A\", \"#6B7684\" )"),
    ("Color var tasa", "5. Tarjetas", "", "Rojo si la tasa sube, verde si baja.",
     "SWITCH ( TRUE (), ISBLANK ( [Var tasa] ), \"#6B7684\", [Var tasa] > 0, \"#B42F2F\", [Var tasa] < 0, \"#0A7D0A\", \"#6B7684\" )"),
    ("Color var % graves", "5. Tarjetas", "", "Rojo si sube la participación de graves.",
     """
     VAR _v = [% graves mes] - [% graves mes anterior]
     RETURN SWITCH ( TRUE (), ISBLANK ( [% graves mes anterior] ), "#6B7684", _v > 0, "#B42F2F", _v < 0, "#0A7D0A", "#6B7684" )"""),

    # ---- 6. Clasificación de clientes (misma regla del pipeline SQL 2.3)
    ("Clasificación", "6. Clasificación", "",
     "Crítico si tasa del mes > 5; Moderado entre 2 y 5; Bajo < 2; Sin dato si no hay trabajadores activos.",
     """
     VAR _t = [Tasa mes]
     RETURN SWITCH ( TRUE (),
         ISBLANK ( [Trabajadores activos] ), "Sin dato",
         _t > 5, "Crítico",
         _t >= 2, "Moderado",
         "Bajo" )"""),
    ("Color clasificación", "6. Clasificación", "", "Color de estado para la clasificación.",
     "SWITCH ( [Clasificación], \"Crítico\", \"#D03B3B\", \"Moderado\", \"#D99A00\", \"Bajo\", \"#0CA30C\", \"#6B7684\" )"),
    ("Clientes críticos", "6. Clasificación", "#,0", "Clientes con tasa del mes de análisis > 5.",
     "COUNTROWS ( FILTER ( VALUES ( Clientes[id_cliente] ), [Clasificación] = \"Crítico\" ) ) + 0"),
    ("Clientes moderados", "6. Clasificación", "#,0", "Clientes con tasa del mes entre 2 y 5.",
     "COUNTROWS ( FILTER ( VALUES ( Clientes[id_cliente] ), [Clasificación] = \"Moderado\" ) ) + 0"),
    ("Clientes bajo", "6. Clasificación", "#,0", "Clientes con tasa del mes menor a 2.",
     "COUNTROWS ( FILTER ( VALUES ( Clientes[id_cliente] ), [Clasificación] = \"Bajo\" ) ) + 0"),
    ("Clientes críticos mes anterior", "6. Clasificación", "#,0", "Clientes críticos en el mes anterior comparable.",
     """
     VAR _ant = EDATE ( [Mes de análisis], -1 )
     RETURN COUNTROWS ( FILTER ( VALUES ( Clientes[id_cliente] ),
         VAR _trab = CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), Calendario[Fecha] = _ant )
         RETURN NOT ISBLANK ( _trab ) && DIVIDE ( [Casos mes anterior], _trab ) * 100 > 5 ) ) + 0"""),
    ("Texto var críticos", "5. Tarjetas", "", "Variación de clientes críticos.",
     """
     VAR _v = [Clientes críticos] - [Clientes críticos mes anterior]
     RETURN IF ( _v > 0, "▲ ", IF ( _v < 0, "▼ ", "= " ) ) & FORMAT ( ABS ( _v ), "#,0", "es-CO" ) & " clientes vs mes ant." """),
    ("Color var críticos", "5. Tarjetas", "", "Rojo si aumentan los clientes críticos.",
     """
     VAR _v = [Clientes críticos] - [Clientes críticos mes anterior]
     RETURN IF ( _v > 0, "#B42F2F", IF ( _v < 0, "#0A7D0A", "#6B7684" ) )"""),

    # ---- 7. Prevención
    ("Actividades prevención", "7. Prevención", "#,0", "Actividades de prevención en el contexto de filtros.",
     "COUNTROWS ( Prevencion )"),
    ("Participantes prevención", "7. Prevención", "#,0", "Participantes en actividades de prevención.",
     "SUM ( Prevencion[Participantes] )"),
    ("Actividades prevención 30 días", "7. Prevención", "#,0", "Actividades en los 30 días que terminan en la fecha de corte (misma ventana del pipeline 2.3).",
     "CALCULATE ( [Actividades prevención], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Fecha corte] - 29, [Fecha corte] ) ) + 0"),
    ("Participantes prevención 30 días", "7. Prevención", "#,0", "Participantes en los últimos 30 días.",
     "CALCULATE ( [Participantes prevención], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Fecha corte] - 29, [Fecha corte] ) ) + 0"),
    ("Clientes sin prevención 30 días", "7. Prevención", "#,0", "Clientes activos sin ninguna actividad de prevención en los últimos 30 días.",
     "COUNTROWS ( FILTER ( VALUES ( Clientes[id_cliente] ), CALCULATE ( SELECTEDVALUE ( Clientes[Estado cliente] ) ) = \"Activo\" && [Actividades prevención 30 días] = 0 ) ) + 0"),
    ("Texto sin prevención", "5. Tarjetas", "", "Texto de apoyo de la tarjeta de prevención.",
     "FORMAT ( [Clientes sin prevención 30 días], \"#,0\", \"es-CO\" ) & \" clientes sin prevención\""),
    ("Color sin prevención", "5. Tarjetas", "", "Rojo si hay clientes sin prevención reciente.",
     "IF ( [Clientes sin prevención 30 días] > 0, \"#B42F2F\", \"#0A7D0A\" )"),
    ("Días sin prevención", "7. Prevención", "#,0", "Días desde la última actividad de prevención hasta la fecha de corte (en blanco si nunca tuvo).",
     """
     VAR _corte = [Fecha corte]
     VAR _ult = CALCULATE ( MAX ( Prevencion[Fecha actividad] ), REMOVEFILTERS ( Calendario ), Calendario[Fecha] <= _corte )
     RETURN IF ( NOT ISBLANK ( _ult ), INT ( _corte - _ult ) )"""),
    ("Actividades por 100 trabajadores 12m", "7. Prevención", "#,0.0", "Intensidad de prevención: actividades de los últimos 12 meses por cada 100 trabajadores activos.",
     """
     VAR _act = CALCULATE ( [Actividades prevención], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], EDATE ( [Fecha corte], -12 ) + 1, [Fecha corte] ) )
     RETURN DIVIDE ( _act, [Trabajadores activos] ) * 100"""),

    # ---- 8. Priorización (últimos 90 días, como la consulta 2.2)
    ("Casos 90 días", "8. Priorización", "#,0", "Casos en los 90 días que terminan en la fecha de corte.",
     "CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], [Fecha corte] - 89, [Fecha corte] ) ) + 0"),
    ("Tasa 90 días", "8. Priorización", "#,0.00", "Tasa mensual de los últimos 90 días: casos 90 d / trabajadores-mes de los 3 últimos periodos × 100.",
     """
     VAR _mesCorte = DATE ( YEAR ( [Fecha corte] ), MONTH ( [Fecha corte] ), 1 )
     VAR _trab = CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], EDATE ( _mesCorte, -2 ), _mesCorte ) )
     RETURN DIVIDE ( [Casos 90 días], _trab ) * 100"""),
    ("Graves abiertos a la fecha", "8. Priorización", "#,0", "Casos graves abiertos de los últimos 12 meses (sin importar el periodo filtrado).",
     "CALCULATE ( [Casos graves abiertos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], EDATE ( [Fecha corte], -12 ) + 1, [Fecha corte] ) ) + 0"),

    # ---- 9. Tendencia (eje desconectado de 12 meses)
    ("Casos tendencia", "9. Tendencia", "#,0", "Casos de cada mes del eje, solo para los 12 meses que terminan en el mes de análisis.",
     """
     VAR _m = SELECTEDVALUE ( 'Eje Periodo'[Inicio mes] )
     VAR _ana = [Mes de análisis]
     RETURN IF ( _m <= _ana && _m > EDATE ( _ana, -12 ),
         CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _m, MIN ( EOMONTH ( _m, 0 ), [Fecha corte] ) ) ) + 0 )"""),
    ("Tasa tendencia", "9. Tendencia", "#,0.00", "Tasa de incidencia de cada mes del eje (12 meses que terminan en el mes de análisis).",
     """
     VAR _m = SELECTEDVALUE ( 'Eje Periodo'[Inicio mes] )
     VAR _ana = [Mes de análisis]
     RETURN IF ( _m <= _ana && _m > EDATE ( _ana, -12 ),
         DIVIDE (
             CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _m, MIN ( EOMONTH ( _m, 0 ), [Fecha corte] ) ) ),
             CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), Calendario[Fecha] = _m ) ) * 100 )"""),
    ("Casos graves tendencia", "9. Tendencia", "#,0", "Casos graves por mes del eje.",
     """
     VAR _m = SELECTEDVALUE ( 'Eje Periodo'[Inicio mes] )
     VAR _ana = [Mes de análisis]
     RETURN IF ( _m <= _ana && _m > EDATE ( _ana, -12 ),
         CALCULATE ( [Casos graves], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], _m, MIN ( EOMONTH ( _m, 0 ), [Fecha corte] ) ) ) + 0 )"""),
    ("Casos leves tendencia", "9. Tendencia", "#,0", "Casos leves por mes del eje.",
     "[Casos tendencia] - [Casos graves tendencia]"),
    ("Promedio histórico casos", "9. Tendencia", "#,0", "Promedio mensual de casos de los meses cerrados disponibles hasta el mes de análisis (referencia de la tendencia).",
     """
     VAR _ana = [Mes de análisis]
     VAR _mesCorte = DATE ( YEAR ( [Fecha corte] ), MONTH ( [Fecha corte] ), 1 )
     VAR _meses = FILTER ( ALL ( 'Eje Periodo'[Inicio mes] ), 'Eje Periodo'[Inicio mes] <= _ana && 'Eje Periodo'[Inicio mes] < _mesCorte )
     RETURN AVERAGEX ( _meses, CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], 'Eje Periodo'[Inicio mes], EOMONTH ( 'Eje Periodo'[Inicio mes], 0 ) ) ) )"""),
    ("Promedio histórico tasa", "9. Tendencia", "#,0.00", "Tasa mensual promedio de los meses cerrados hasta el mes de análisis.",
     """
     VAR _ana = [Mes de análisis]
     VAR _mesCorte = DATE ( YEAR ( [Fecha corte] ), MONTH ( [Fecha corte] ), 1 )
     VAR _fin = MIN ( EOMONTH ( _ana, 0 ), _mesCorte - 1 )
     RETURN DIVIDE (
         CALCULATE ( [Total casos], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], BLANK (), _fin ) ),
         CALCULATE ( [Trabajadores-mes], REMOVEFILTERS ( Calendario ), DATESBETWEEN ( Calendario[Fecha], BLANK (), _fin ) ) ) * 100"""),
    ("Subtítulo tendencia casos", "9. Tendencia", "", "Explica la línea de referencia de la tendencia de casos.",
     "\"Línea punteada = promedio histórico mensual (meses cerrados): \" & FORMAT ( [Promedio histórico casos], \"#,0\", \"es-CO\" ) & \" casos\""),
    ("Subtítulo tendencia tasa", "9. Tendencia", "", "Explica la línea de referencia de la tendencia de la tasa.",
     "\"Línea punteada = tasa promedio histórica (meses cerrados): \" & FORMAT ( [Promedio histórico tasa], \"#,0.00\", \"es-CO\" )"),
    ("Título tasa", "9. Tendencia", "", "Título dinámico de la tendencia de la tasa.",
     """
     "Tasa de incidencia por mes (casos x 100 trabajadores)"
         & IF ( [Es mes en curso] = 1, " · el último mes es parcial", "" )"""),
    ("Color barra tendencia", "9. Tendencia", "", "Azul para meses cerrados; azul claro para el mes en curso (parcial).",
     """
     VAR _m = SELECTEDVALUE ( 'Eje Periodo'[Inicio mes] )
     RETURN IF ( EOMONTH ( _m, 0 ) > [Fecha corte], "#86B6EF", "#0055A0" )"""),
    ("Título tendencia", "9. Tendencia", "", "Título dinámico de la tendencia.",
     """
     "Casos por mes · 12 meses hasta " & LOOKUPVALUE ( Calendario[Periodo], Calendario[Fecha], [Mes de análisis] )
         & IF ( [Es mes en curso] = 1, " (barra clara = mes en curso, parcial)", "" )"""),

    # ---- 10. Medidas literales de la pregunta 1.5 (para la página de notas técnicas)
    ("A · Casos YTD (literal)", "10. Pregunta 1.5", "#,0",
     "Medida A tal como está en la prueba: cuenta id_caso (incluye anulados) acumulado en el año.",
     "TOTALYTD ( COUNT ( Casos[ID caso] ), Calendario[Fecha] )"),
    ("B · % participación sin ALL", "10. Pregunta 1.5", "0.0 %",
     "Demostración: la Medida B sin ALL(clientes) siempre da 100 % en cada fila.",
     "DIVIDE ( [Total casos], CALCULATE ( [Total casos] ), 0 )"),
    ("C · Var vs mes anterior (literal)", "10. Pregunta 1.5", "+#,0;-#,0;0",
     "Medida C tal como está en la prueba: casos del mes menos casos del mes anterior con PREVIOUSMONTH.",
     "[Total casos] - CALCULATE ( [Total casos], PREVIOUSMONTH ( Calendario[Fecha] ) )"),
    ("C · Var vs mes anterior (corregida)", "10. Pregunta 1.5", "+#,0;-#,0;0",
     "Medida C robusta: en blanco si no existe mes anterior en el calendario y 0 explícito si existe pero no tuvo casos.",
     """
     VAR _act = [Total casos] + 0
     VAR _hayAnterior = NOT ISEMPTY ( PREVIOUSMONTH ( Calendario[Fecha] ) )
     VAR _ant = CALCULATE ( [Total casos], PREVIOUSMONTH ( Calendario[Fecha] ) ) + 0
     RETURN IF ( _hayAnterior && HASONEVALUE ( Calendario[Inicio mes] ), _act - _ant )"""),
]


def medidas_tmdl() -> str:
    partes = ["table _Medidas", f"\tlineageTag: {tag('_Medidas')}", ""]
    for nombre, carpeta, fmt, desc, expr in MEDIDAS:
        expr = dedent(expr).strip("\n")
        partes.append(f"\t/// {desc}")
        if "\n" in expr:
            partes.append(f"\tmeasure {q(nombre)} =")
            partes.append(indent(expr, "\t\t\t"))
        else:
            partes.append(f"\tmeasure {q(nombre)} = {expr}")
        if fmt:
            partes.append(f"\t\tformatString: {valor_tmdl(fmt)}")
        partes.append(f"\t\tdisplayFolder: {carpeta}")
        partes.append(f"\t\tlineageTag: {tag('m.' + nombre)}")
        partes.append("")
    # columna ficticia oculta para que la tabla de medidas exista con partición
    partes.append("\tcolumn Columna")
    partes.append("\t\tisHidden")
    partes.append(f"\t\tlineageTag: {tag('_Medidas.Columna')}")
    partes.append("\t\tsummarizeBy: none")
    partes.append("\t\tisNameInferred")
    partes.append("\t\tsourceColumn: [Columna]")
    partes.append("")
    partes.append("\tpartition _Medidas = calculated")
    partes.append("\t\tmode: import")
    partes.append("\t\tsource = ROW ( \"Columna\", BLANK () )")
    partes.append("")
    return "\n".join(partes) + "\n"


RELACIONES = [
    ("Casos", "id_cliente", "Clientes", "id_cliente"),
    ("Facturacion", "id_cliente", "Clientes", "id_cliente"),
    ("Prevencion", "id_cliente", "Clientes", "id_cliente"),
    ("Casos", "Fecha ocurrencia", "Calendario", "Fecha"),
    ("Facturacion", "Periodo", "Calendario", "Fecha"),
    ("Prevencion", "Fecha actividad", "Calendario", "Fecha"),
]


def relaciones_tmdl() -> str:
    out = []
    for ft, fc, tt, tc in RELACIONES:
        out.append(f"relationship {tag(f'rel.{ft}.{fc}')}")
        out.append(f"\tfromColumn: {q(ft)}.{q(fc)}")
        out.append(f"\ttoColumn: {q(tt)}.{q(tc)}")
        out.append("")
    return "\n".join(out) + "\n"


ROLES = {
    "Coordinador": (
        "Cada coordinador ve solo los clientes que tiene asignados (seguridad dinámica por correo).",
        {
            "Clientes": "[id_cliente] IN CALCULATETABLE ( VALUES ( 'Seguridad Asignacion'[id_cliente] ), 'Seguridad Asignacion'[Correo] = LOWER ( USERPRINCIPALNAME () ) )",
            "Seguridad Asignacion": "[Correo] = LOWER ( USERPRINCIPALNAME () )",
        }),
    "Gerencia": ("Acceso a todos los clientes.", {}),
}


def roles_tmdl() -> dict[str, str]:
    out = {}
    for nombre, (desc, permisos) in ROLES.items():
        lineas = [f"/// {desc}", f"role {q(nombre)}", "\tmodelPermission: read", ""]
        for tabla, expr in permisos.items():
            lineas.append(f"\ttablePermission {q(tabla)} = {expr}")
            lineas.append("")
        lineas.append(f"\tannotation PBI_Id = {tag('role.' + nombre).replace('-', '')}")
        out[nombre] = "\n".join(lineas) + "\n"
    return out


def modelo_tmdl(nombres_tablas: list[str]) -> str:
    lineas = [
        "model Model",
        "\tculture: es-CO",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: es-CO",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        "annotation PBI_ProTooling = [\"DevMode\"]",
        "",
    ]
    for t in nombres_tablas:
        lineas.append(f"ref table {q(t)}")
    lineas.append("")
    for r in ROLES:
        lineas.append(f"ref role {q(r)}")
    lineas.append("")
    return "\n".join(lineas) + "\n"


def expresiones_tmdl(ruta_datos: str) -> str:
    ruta = ruta_datos.replace('"', '""')
    return (f'/// Carpeta donde están los CSV generados por datos/generar_datos.py (debe terminar en \\).\n'
            f'expression RutaDatos = "{ruta}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
            f"\tlineageTag: {tag('expr.RutaDatos')}\n\n"
            "\tannotation PBI_ResultType = Text\n\n"
            "\tannotation PBI_NavigationStepName = Navegación\n")
