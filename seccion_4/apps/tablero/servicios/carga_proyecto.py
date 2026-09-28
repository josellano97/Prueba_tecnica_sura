"""
Carga de la fuente oficial del proyecto (datos/salida/*.csv: la misma que usan el SQL y el Power BI).

Pasos: leer → validar → transformar a grano cliente × mes → guardar. Cada problema de calidad se cuenta,
se le asigna un tratamiento explícito y queda registrado en CargaDatos.calidad (no se oculta nada).

Reglas de tratamiento (coherentes con las Secciones 1 a 3 de la prueba):
* Casos anulados: no son incidentes; se excluyen de todos los indicadores y se reportan.
* Mes de la fecha de corte incompleto: se excluye de los indicadores mensuales (se reporta cuántos casos quedan fuera).
* Tipo 'grave'/'leve': se respeta el campo oficial aunque los días de ausencia no concuerden (se reporta).
* Costos extremos: se conservan (son válidos) y se señalan para revisión.
* Casos sin exposición (sin facturación ese mes): no pueden entrar en la tasa; se excluyen y se reportan.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import quantiles

from django.db import transaction

from ..models import Caso, CargaDatos, Cliente, Coordinador, IndicadorMensual, Sector

ARCHIVOS = ["clientes", "casos", "facturacion", "prevencion", "coordinadores", "asignacion_coordinador"]
VARIABLES = ["dias_ausencia", "casos_abiertos", "casos_anulados", "actividades_prevencion", "valor_contrato",
             "detalle_casos", "coordinador_regional"]


class ErrorCarga(Exception):
    pass


def _leer(origen: Path, nombre: str) -> list[dict]:
    ruta = origen / f"{nombre}.csv"
    if not ruta.exists():
        raise ErrorCarga(f"No se encontró {ruta}. Genere los datos con: python datos/generar_datos.py")
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _fecha(txt: str) -> date | None:
    try:
        return date.fromisoformat(txt.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _mes(d: date) -> date:
    return d.replace(day=1)


def _fin_mes(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


class Hallazgos:
    """Acumula hallazgos de calidad con severidad, tratamiento y KPIs afectados."""

    def __init__(self):
        self.items: list[dict] = []

    def agregar(self, codigo, severidad, descripcion, registros, tratamiento, afecta=(), ejemplos=()):
        self.items.append({"codigo": codigo, "severidad": severidad, "descripcion": descripcion,
                           "registros": registros, "tratamiento": tratamiento, "afecta": list(afecta),
                           "ejemplos": [str(e) for e in list(ejemplos)[:5]]})


def cargar(origen: Path) -> CargaDatos:
    origen = Path(origen)
    datos = {n: _leer(origen, n) for n in ARCHIVOS}
    corte_txt = (origen / "fecha_corte.txt").read_text(encoding="utf-8").strip() if (origen / "fecha_corte.txt").exists() else ""
    h = Hallazgos()

    casos_fechas = [_fecha(r["fecha_ocurrencia"]) for r in datos["casos"]]
    corte = _fecha(corte_txt) or max(f for f in casos_fechas if f)
    if not corte_txt:
        h.agregar("SIN_FECHA_CORTE", "advertencia", "La fuente no declara fecha de corte.", 1,
                  "Se usa la fecha del último caso registrado.")
    ultimo_cerrado = _mes(corte) if corte == _fin_mes(corte) else _mes(_mes(corte) - timedelta(days=1))

    # ---------------- clientes, coordinadores y asignación
    coords = {r["id_coordinador"]: r for r in datos["coordinadores"]}
    asignacion = {r["id_cliente"]: r["id_coordinador"] for r in datos["asignacion_coordinador"]}
    clientes = {}
    invalidos = []
    for r in datos["clientes"]:
        try:
            clase = int(r["clase_riesgo"])
        except ValueError:
            clase = None
        if clase not in range(1, 6) or r["estado"] not in ("activo", "inactivo"):
            invalidos.append(r["id_cliente"])
            continue
        clientes[r["id_cliente"]] = r
    if invalidos:
        h.agregar("CLIENTE_INVALIDO", "critico", "Clientes con clase de riesgo o estado fuera de dominio.", len(invalidos),
                  "Se excluyen (sin clase no se pueden clasificar).", ["todos"], invalidos)
    sin_coord = [c for c in clientes if c not in asignacion]
    if sin_coord:
        h.agregar("CLIENTE_SIN_COORDINADOR", "advertencia", "Clientes sin coordinador asignado.", len(sin_coord),
                  "Se cargan sin coordinador: solo los ven usuarios con permiso de ver todos los clientes.", [], sin_coord)

    # ---------------- facturación = exposición (trabajadores) y valor
    fact = {}
    dup_fact, parcial_fact, huerf_fact, malos_fact = 0, 0, 0, 0
    for r in datos["facturacion"]:
        p = _fecha(r["periodo"])
        clave = (r["id_cliente"], p)
        if r["id_cliente"] not in clientes:
            huerf_fact += 1
            continue
        try:
            trab, valor = int(r["trabajadores_activos"]), Decimal(r["valor_contrato"])
        except (ValueError, ArithmeticError):
            trab, valor = -1, Decimal(-1)
        if p is None or p.day != 1 or trab <= 0 or valor < 0:
            malos_fact += 1
            continue
        if p > ultimo_cerrado:
            parcial_fact += 1
            continue
        if clave in fact:
            dup_fact += 1
            continue
        fact[clave] = (trab, valor)
    for cod, n, desc, trat, sev in [
        ("FACTURACION_DUPLICADA", dup_fact, "Periodos facturados dos veces para el mismo cliente.", "Se conserva el primero.", "critico"),
        ("FACTURACION_INVALIDA", malos_fact, "Periodos con fecha inválida, trabajadores ≤ 0 o valor negativo.", "Se excluyen.", "critico"),
        ("FACTURACION_SIN_CLIENTE", huerf_fact, "Facturación de clientes inexistentes.", "Se excluye.", "critico"),
    ]:
        if n:
            h.agregar(cod, sev, desc, n, trat, ["tasa de incidencia", "trabajadores"])
    if parcial_fact:
        h.agregar("MES_EN_CURSO", "info",
                  f"El mes de la fecha de corte ({corte:%m/%Y}) está incompleto: datos hasta el {corte:%d/%m/%Y}.",
                  parcial_fact, f"Se excluye de los indicadores mensuales; el último mes analizado es {ultimo_cerrado:%m/%Y}.",
                  ["todos los indicadores mensuales"])

    # ---------------- casos
    ids = Counter(r["id_caso"] for r in datos["casos"])
    dups = [i for i, n in ids.items() if n > 1]
    if dups:
        h.agregar("CASO_DUPLICADO", "critico", "id_caso repetido.", len(dups), "Se conserva el primero.", ["casos"], dups)
    agregados = defaultdict(lambda: {"casos": 0, "graves": 0, "costo_leve": Decimal(0), "costo_grave": Decimal(0),
                                     "dias": 0, "abiertos": 0, "graves_abiertos": 0, "anulados": 0})
    detalle, vistos = [], set()
    cont = Counter()
    ej = defaultdict(list)
    costos_tipo = defaultdict(list)
    for r in datos["casos"]:
        if r["id_caso"] in vistos:
            continue
        vistos.add(r["id_caso"])
        f = _fecha(r["fecha_ocurrencia"])
        if r["id_cliente"] not in clientes:
            cont["sin_cliente"] += 1
            continue
        try:
            dias, costo = int(r["dias_ausencia"]), Decimal(r["costo"])
        except (ValueError, ArithmeticError):
            dias, costo = -1, Decimal(-1)
        tipo, estado = r["tipo"].strip().lower(), r["estado"].strip().lower()
        if f is None or f > corte:
            cont["fecha_invalida"] += 1; ej["fecha_invalida"].append(r["id_caso"]); continue
        if dias < 0 or costo < 0 or tipo not in ("leve", "grave") or estado not in ("abierto", "cerrado", "anulado"):
            cont["valor_invalido"] += 1; ej["valor_invalido"].append(r["id_caso"]); continue
        detalle.append((r, f, tipo, estado, dias, costo))
        if estado == "anulado":
            cont["anulados"] += 1
        else:
            if (tipo == "grave") != (dias > 15):
                cont["tipo_vs_dias"] += 1; ej["tipo_vs_dias"].append(r["id_caso"])
            costos_tipo[tipo].append((float(costo), r["id_caso"]))
        p = _mes(f)
        if p > ultimo_cerrado:
            if estado != "anulado":
                cont["mes_en_curso"] += 1
            continue
        a = agregados[(r["id_cliente"], p)]
        if estado == "anulado":
            a["anulados"] += 1
            continue
        if (r["id_cliente"], p) not in fact:
            cont["sin_exposicion"] += 1; ej["sin_exposicion"].append(r["id_caso"])
        a["casos"] += 1
        a["dias"] += dias
        if tipo == "grave":
            a["graves"] += 1; a["costo_grave"] += costo
        else:
            a["costo_leve"] += costo
        if estado == "abierto":
            a["abiertos"] += 1
            if tipo == "grave":
                a["graves_abiertos"] += 1
    atipicos = 0
    for tipo, valores in costos_tipo.items():
        if len(valores) >= 20:
            q1, _, q3 = quantiles([v for v, _ in valores], n=4)
            lim = q3 + 3 * (q3 - q1)
            fuera = [i for v, i in valores if v > lim]
            atipicos += len(fuera)
            ej["costo_atipico"] += fuera
    reglas = [
        ("CASO_SIN_CLIENTE", "sin_cliente", "critico", "Casos de clientes inexistentes.", "Se excluyen.", ["casos"]),
        ("CASO_FECHA_INVALIDA", "fecha_invalida", "critico", "Casos sin fecha o con fecha posterior al corte.", "Se excluyen.", ["casos"]),
        ("CASO_VALOR_INVALIDO", "valor_invalido", "critico", "Días o costo negativos, o tipo/estado fuera de dominio.", "Se excluyen.", ["casos", "costo"]),
        ("CASO_ANULADO", "anulados", "info", "Registros anulados.", "No son incidentes: se excluyen de todos los indicadores.", ["casos", "costo", "tasa"]),
        ("TIPO_VS_DIAS", "tipo_vs_dias", "advertencia",
         "El tipo del caso no concuerda con los días de ausencia (grave con ≤ 15 días o leve con > 15).",
         "Se respeta el campo oficial 'tipo'; los días se usan solo para severidad. Validar la regla de clasificación con el área dueña.",
         ["% casos graves"]),
        ("CASO_MES_EN_CURSO", "mes_en_curso", "info", "Casos del mes incompleto de la fecha de corte.", "Quedan fuera de los indicadores mensuales.", ["casos del mes"]),
        ("CASO_SIN_EXPOSICION", "sin_exposicion", "critico", "Casos en meses sin facturación del cliente (no hay trabajadores para la tasa).",
         "Se cuentan en casos, pero no en la tasa.", ["tasa de incidencia"]),
    ]
    for cod, clave, sev, desc, trat, afecta in reglas:
        if cont[clave]:
            h.agregar(cod, sev, desc, cont[clave], trat, afecta, ej[clave])
    if atipicos:
        h.agregar("COSTO_ATIPICO", "advertencia", "Casos con costo extremo (mayor a Q3 + 3·IQR de su tipo).", atipicos,
                  "Se conservan (son válidos), pero pesan mucho en el costo: revisar antes de concluir sobre costos.",
                  ["costo total", "costo por caso"], ej["costo_atipico"])

    # ---------------- prevención
    prev = defaultdict(lambda: [0, 0])
    prev_fuera = 0
    for r in datos["prevencion"]:
        f = _fecha(r["fecha"])
        if r["id_cliente"] not in clientes or f is None or f > corte:
            prev_fuera += 1
            continue
        if _mes(f) <= ultimo_cerrado:
            prev[(r["id_cliente"], _mes(f))][0] += 1
            prev[(r["id_cliente"], _mes(f))][1] += int(r["participantes"] or 0)
    if prev_fuera:
        h.agregar("PREVENCION_INVALIDA", "advertencia", "Actividades sin cliente o con fecha inválida.", prev_fuera, "Se excluyen.", ["cobertura de prevención"])
    h.agregar("SIN_METAS", "info", "La fuente no contiene metas ni presupuesto por indicador.", 0,
              "Los indicadores se muestran como descriptivos (sin % de cumplimiento). Solo la clasificación crítico/moderado/bajo usa una regla oficial.",
              ["cumplimiento"])

    with transaction.atomic():
        IndicadorMensual.objects.all().delete()
        Caso.objects.all().delete()
        Cliente.objects.all().delete()
        CargaDatos.objects.all().delete()
        sectores = {n: Sector.objects.get_or_create(nombre=n)[0] for n in sorted({c["sector"] for c in clientes.values()})}
        objs_coord = {}
        for idc, r in coords.items():
            obj, _ = Coordinador.objects.update_or_create(nombre=r["nombre_coordinador"], defaults={"correo": r["correo"], "regional": r["regional"]})
            objs_coord[idc] = obj
        objs = {}
        for idc, r in clientes.items():
            objs[idc] = Cliente.objects.create(
                nombre=r["nombre"], sector=sectores[r["sector"]], clase_riesgo=int(r["clase_riesgo"]),
                coordinador=objs_coord.get(asignacion.get(idc)), activo=r["estado"] == "activo",
                fecha_vinculacion=_fecha(r["fecha_vinculacion"]))
        filas = []
        for (idc, p), (trab, valor) in fact.items():
            a = agregados.get((idc, p))
            pv = prev.get((idc, p), (0, 0))
            filas.append(IndicadorMensual(
                cliente=objs[idc], periodo=p, trabajadores_activos=trab,
                casos=a["casos"] if a else 0, casos_graves=a["graves"] if a else 0,
                costo_leve=a["costo_leve"] if a else 0, costo_grave=a["costo_grave"] if a else 0,
                dias_ausencia=a["dias"] if a else 0, casos_abiertos=a["abiertos"] if a else 0,
                casos_graves_abiertos=a["graves_abiertos"] if a else 0, casos_anulados=a["anulados"] if a else 0,
                actividades_prevencion=pv[0], participantes_prevencion=pv[1], valor_contrato=valor))
        IndicadorMensual.objects.bulk_create(filas, batch_size=1000)
        Caso.objects.bulk_create([
            Caso(id_origen=int(r["id_caso"]), cliente=objs[r["id_cliente"]], fecha=f, tipo=tipo, dias_ausencia=dias,
                 costo=costo, estado=estado) for r, f, tipo, estado, dias, costo in detalle], batch_size=2000)
        periodos = sorted(p for _, p in fact)
        carga = CargaDatos.objects.create(
            fuente="proyecto", descripcion=f"Fuente oficial del proyecto ({origen.name}): la misma del SQL y el Power BI",
            fecha_corte=corte, periodo_desde=periodos[0], periodo_hasta=periodos[-1], variables=VARIABLES,
            calidad={"hallazgos": h.items, "resumen": {
                "clientes": len(objs), "casos_leidos": len(datos["casos"]), "casos_validos_en_indicadores": sum(a["casos"] for a in agregados.values()),
                "registros_mensuales": len(filas), "actividades_prevencion": sum(v[0] for v in prev.values()),
                "no_utilizados": ["trabajadores.csv: la exposición se toma de facturación (fuente oficial del denominador de la tasa)"]}})
    return carga
