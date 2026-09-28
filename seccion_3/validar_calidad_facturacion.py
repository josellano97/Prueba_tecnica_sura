"""
Validación de calidad del archivo de facturación antes de entrar al pipeline.

Simula el control que correría automáticamente con cada carga nueva:

  1. (Opcional) Genera un archivo de prueba con 1.000+ registros y problemas intencionales:
     IDs con formatos inconsistentes, periodos en distintos formatos de fecha, valores
     negativos o nulos en campos críticos y duplicados por cliente + periodo.
  2. Normaliza lo que se puede normalizar sin adivinar (ID y periodo) y valida 5 dimensiones:
       Completitud  - campos obligatorios sin nulos
       Validez      - valores dentro de rangos y formatos esperados
       Unicidad     - sin duplicados por id_cliente + periodo
       Consistencia - trabajadores_activos > 0 cuando valor_contrato > 0
       Oportunidad  - periodo no futuro ni con más de 60 días de atraso
  3. Genera un reporte JSON: score por dimensión, totales, válidos y rechazados por regla.
  4. Exporta los válidos a Parquet y los rechazados a Excel con la razón del rechazo.

Uso rápido:
    python seccion_3/validar_calidad_facturacion.py                       # genera y valida
    python seccion_3/validar_calidad_facturacion.py --entrada archivo.csv # valida una carga real

Códigos de salida (para el orquestador):
    0 = carga aprobada | 2 = carga rechazada por calidad (score < umbral) | 1 = error de ejecución
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

LOG = logging.getLogger("calidad_facturacion")

COLUMNAS = ["id_cliente", "periodo", "trabajadores_activos", "valor_contrato"]
VALORES_NULOS = {"", "null", "none", "nan", "nat", "n/a", "na", "n/d", "nd", "-", "sin dato"}
MAX_TRABAJADORES = 100_000
MAX_VALOR_CONTRATO = 50_000_000_000        # 50 mil millones: tope de razonabilidad
MAX_DIAS_ATRASO = 60

# Catálogo de reglas: código -> (dimensión, descripción legible para el Excel de rechazos)
REGLAS: dict[str, tuple[str, str]] = {
    "COM_ID_NULO":           ("Completitud", "id_cliente vacío"),
    "COM_PERIODO_NULO":      ("Completitud", "periodo vacío"),
    "COM_TRABAJADORES_NULO": ("Completitud", "trabajadores_activos vacío"),
    "COM_VALOR_NULO":        ("Completitud", "valor_contrato vacío"),
    "VAL_ID_FORMATO":        ("Validez", "id_cliente con formato no reconocible"),
    "VAL_PERIODO_FORMATO":   ("Validez", "periodo con formato de fecha no reconocible o fecha inexistente"),
    "VAL_TRABAJADORES_RANGO": ("Validez", f"trabajadores_activos no es entero entre 0 y {MAX_TRABAJADORES:,}"),
    "VAL_VALOR_RANGO":       ("Validez", "valor_contrato no numérico, negativo o fuera de rango"),
    "UNI_DUPLICADO_EXACTO":  ("Unicidad", "duplicado exacto de otro registro (se conserva solo el primero)"),
    "UNI_DUPLICADO_CONFLICTO": ("Unicidad", "mismo cliente + periodo con valores distintos (no se sabe cuál es el correcto)"),
    "CON_TRABAJADORES_CERO": ("Consistencia", "valor_contrato > 0 pero trabajadores_activos = 0"),
    "OPO_PERIODO_FUTURO":    ("Oportunidad", "periodo posterior al mes de la carga"),
    "OPO_ATRASO_MAYOR_60D":  ("Oportunidad", f"el periodo cerró hace más de {MAX_DIAS_ATRASO} días"),
}
DIMENSIONES = ["Completitud", "Validez", "Unicidad", "Consistencia", "Oportunidad"]
MESES_ES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
            "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}


class ErrorCarga(Exception):
    """Error que impide validar el archivo (no es un problema de calidad de registros)."""


@dataclass
class Configuracion:
    fecha_referencia: date
    umbral_aprobacion: float = 0.90       # % mínimo de registros válidos para aprobar la carga
    base_atraso: str = "fin"              # 'fin' (fin de mes del periodo) o 'inicio'


# ---------------------------------------------------------------------------
# 1. Generación del archivo de prueba
# ---------------------------------------------------------------------------
def _mes(d: date, desplazamiento: int) -> date:
    total = d.year * 12 + d.month - 1 + desplazamiento
    return date(total // 12, total % 12 + 1, 1)


def _formato_id(rng, idc: int) -> str:
    return rng.choice([f"CLI-{idc:04d}", f" {idc} ", f"{idc:05d}", f"cli_{idc}", f"{idc}.0", f"C{idc}"])


def _formato_periodo(rng, p: date) -> str:
    abrev = [k for k, v in MESES_ES.items() if v == p.month][0]
    return rng.choice([p.strftime("%d/%m/%Y"), p.strftime("%Y/%m"), p.strftime("%m-%Y"),
                       p.strftime("%Y%m"), f"{abrev}-{p.year}", p.replace(day=15).isoformat()])


def generar_archivo_prueba(ruta: Path, n_clientes: int, fecha_ref: date, semilla: int = 42) -> pd.DataFrame:
    """Crea un CSV de facturación con ~2 periodos por cliente y problemas intencionales."""
    rng = np.random.default_rng(semilla)
    periodos = [_mes(fecha_ref, -1), _mes(fecha_ref, 0)]
    filas = []
    for idc in range(1, n_clientes + 1):
        trab = int(np.clip(rng.lognormal(4.5, 0.9), 5, 5000))
        for p in periodos:
            filas.append({"id_cliente": str(idc), "periodo": p.isoformat(),
                          "trabajadores_activos": str(trab + int(rng.integers(-3, 4))),
                          "valor_contrato": f"{round(trab * rng.uniform(40_000, 130_000), -3):.0f}"})
    df = pd.DataFrame(filas)
    n = len(df)

    def muestra(frac):
        return rng.choice(n, size=int(n * frac), replace=False)

    # IDs con formatos inconsistentes (válidos tras normalizar) e IDs irrecuperables
    for i in muestra(0.10):
        df.at[i, "id_cliente"] = _formato_id(rng, int(df.at[i, "id_cliente"]))
    for i in muestra(0.012):
        df.at[i, "id_cliente"] = rng.choice(["ABC", "-15", "CLIENTE", "12-A"])
    # Periodos en diferentes formatos y algunos inválidos
    for i in muestra(0.25):
        df.at[i, "periodo"] = _formato_periodo(rng, date.fromisoformat(df.at[i, "periodo"]))
    for i in muestra(0.01):
        df.at[i, "periodo"] = rng.choice(["2026-13-01", "31/02/2026", "sin periodo", "2026-00"])
    # Oportunidad: periodos futuros y demasiado atrasados
    for i in muestra(0.02):
        df.at[i, "periodo"] = _mes(fecha_ref, int(rng.integers(2, 6))).isoformat()
    for i in muestra(0.03):
        df.at[i, "periodo"] = _mes(fecha_ref, -int(rng.integers(3, 10))).isoformat()
    # Nulos en campos críticos
    for col, frac in [("id_cliente", 0.01), ("periodo", 0.01), ("trabajadores_activos", 0.02),
                      ("valor_contrato", 0.02)]:
        for i in muestra(frac):
            df.at[i, col] = rng.choice(["", "NULL", "N/D"])
    # Valores negativos
    for i in muestra(0.02):
        df.at[i, "trabajadores_activos"] = str(-int(rng.integers(1, 50)))
    for i in muestra(0.02):
        df.at[i, "valor_contrato"] = f"-{df.at[i, 'valor_contrato']}".replace("--", "-")
    # Inconsistencia: contrato con valor pero 0 trabajadores
    for i in muestra(0.02):
        df.at[i, "trabajadores_activos"] = "0"
    # Duplicados por cliente + periodo: exactos (a veces con otro formato de ID) y en conflicto
    base = df.iloc[muestra(0.05)].copy()
    mitad = len(base) // 2
    exactos = base.iloc[:mitad].copy()
    exactos["id_cliente"] = [_formato_id(rng, int(x)) if str(x).strip().isdigit() else x
                             for x in exactos["id_cliente"]]
    conflicto = base.iloc[mitad:].copy()
    conflicto["valor_contrato"] = [f"{float(v) * 1.1:.0f}" if re.fullmatch(r"-?\d+(\.\d+)?", str(v)) else v
                                   for v in conflicto["valor_contrato"]]
    df = pd.concat([df, exactos, conflicto], ignore_index=True)
    df = df.sample(frac=1, random_state=semilla).reset_index(drop=True)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8")
    LOG.info("Archivo de prueba generado: %s (%d registros)", ruta, len(df))
    return df


# ---------------------------------------------------------------------------
# 2. Carga y normalización
# ---------------------------------------------------------------------------
def cargar_archivo(ruta: Path) -> pd.DataFrame:
    """Lee el archivo como texto (sin inferir tipos) y valida el esquema mínimo."""
    if not ruta.exists():
        raise ErrorCarga(f"No existe el archivo de entrada: {ruta}")
    try:
        if ruta.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(ruta, dtype=str, keep_default_na=False)
        else:
            try:
                df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="latin-1")
    except Exception as exc:                      # archivo corrupto, separador inválido, etc.
        raise ErrorCarga(f"No se pudo leer {ruta.name}: {exc}") from exc
    df.columns = [c.strip().lower() for c in df.columns]
    faltantes = [c for c in COLUMNAS if c not in df.columns]
    if faltantes:
        raise ErrorCarga(f"Faltan columnas obligatorias: {faltantes}. Columnas recibidas: {list(df.columns)}")
    if df.empty:
        raise ErrorCarga("El archivo no tiene registros.")
    df = df[COLUMNAS].copy()
    df.insert(0, "fila_origen", np.arange(2, len(df) + 2))      # fila en el archivo (1 = encabezado)
    return df


def es_nulo(valor) -> bool:
    return valor is None or (isinstance(valor, float) and np.isnan(valor)) or \
        str(valor).strip().lower() in VALORES_NULOS


def normalizar_id(valor: str) -> int | None:
    """'CLI-0012', ' 12 ', '00012', 'cli_12', '12.0', 'C12' -> 12. Devuelve None si no es reconocible."""
    s = str(valor).strip().upper()
    m = re.fullmatch(r"(?:(?:CLI(?:ENTE)?|C)[\s_\-]*)?0*(\d{1,6})(?:\.0+)?", s)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def normalizar_periodo(valor: str) -> tuple[date | None, bool]:
    """Convierte formatos habituales al primer día del mes.

    Devuelve (periodo, ajustado) donde ajustado=True si la fecha traía un día distinto de 1.
    Supuesto: en formatos dd/mm/aaaa el día va primero (convención colombiana).
    """
    s = str(valor).strip().lower()
    formatos = ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m", "%Y/%m", "%m/%Y", "%m-%Y", "%Y%m"]
    for fmt in formatos:
        try:
            d = datetime.strptime(s, fmt).date()
            return d.replace(day=1), d.day != 1
        except ValueError:
            continue
    m = re.fullmatch(r"([a-z]{3})[a-z]*[\s\-/]+(\d{4})", s) or re.fullmatch(r"(\d{4})[\s\-/]+([a-z]{3})[a-z]*", s)
    if m:
        partes = m.groups()
        mes_txt, anio = (partes[0], partes[1]) if partes[0].isalpha() else (partes[1], partes[0])
        if mes_txt in MESES_ES:
            return date(int(anio), MESES_ES[mes_txt], 1), False
    return None, False


def a_numero(valor) -> float | None:
    try:
        x = float(str(valor).strip())
        return x if np.isfinite(x) else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3. Reglas de calidad
# ---------------------------------------------------------------------------
def fin_de_mes(d: date) -> date:
    return _mes(d, 1) - timedelta(days=1)


def validar(df: pd.DataFrame, cfg: Configuracion) -> pd.DataFrame:
    """Aplica todas las reglas. Agrega columnas normalizadas, 'reglas' (lista) y 'advertencias'."""
    r = df.copy()
    reglas = [[] for _ in range(len(r))]
    advert = [[] for _ in range(len(r))]
    evaluado = {d: np.zeros(len(r), dtype=bool) for d in DIMENSIONES}
    ids, periodos, trabs, valores = [], [], [], []

    for i, fila in enumerate(r.itertuples(index=False)):
        # --- Completitud (siempre evaluable)
        evaluado["Completitud"][i] = True
        nulos = {c: es_nulo(getattr(fila, c)) for c in COLUMNAS}
        for c, cod in [("id_cliente", "COM_ID_NULO"), ("periodo", "COM_PERIODO_NULO"),
                       ("trabajadores_activos", "COM_TRABAJADORES_NULO"), ("valor_contrato", "COM_VALOR_NULO")]:
            if nulos[c]:
                reglas[i].append(cod)
        # --- Validez (solo sobre campos presentes)
        idc = per = trab = val = None
        if not all(nulos.values()):
            evaluado["Validez"][i] = True
        if not nulos["id_cliente"]:
            idc = normalizar_id(fila.id_cliente)
            if idc is None:
                reglas[i].append("VAL_ID_FORMATO")
            elif str(fila.id_cliente).strip() != str(idc):
                advert[i].append("ID estandarizado")
        if not nulos["periodo"]:
            per, ajustado = normalizar_periodo(fila.periodo)
            if per is None:
                reglas[i].append("VAL_PERIODO_FORMATO")
            elif str(fila.periodo).strip() != per.isoformat():
                advert[i].append("Periodo estandarizado" + (" (día distinto de 1)" if ajustado else ""))
        if not nulos["trabajadores_activos"]:
            t = a_numero(fila.trabajadores_activos)
            if t is None or t != int(t) or not 0 <= t <= MAX_TRABAJADORES:
                reglas[i].append("VAL_TRABAJADORES_RANGO")
            else:
                trab = int(t)
        if not nulos["valor_contrato"]:
            v = a_numero(fila.valor_contrato)
            if v is None or not 0 <= v <= MAX_VALOR_CONTRATO:
                reglas[i].append("VAL_VALOR_RANGO")
            else:
                val = v
        # --- Consistencia (requiere ambos numéricos válidos)
        if trab is not None and val is not None:
            evaluado["Consistencia"][i] = True
            if val > 0 and trab == 0:
                reglas[i].append("CON_TRABAJADORES_CERO")
        # --- Oportunidad (requiere periodo válido)
        if per is not None:
            evaluado["Oportunidad"][i] = True
            mes_ref = cfg.fecha_referencia.replace(day=1)
            if per > mes_ref:
                reglas[i].append("OPO_PERIODO_FUTURO")
            else:
                base = fin_de_mes(per) if cfg.base_atraso == "fin" else per
                if (cfg.fecha_referencia - base).days > MAX_DIAS_ATRASO:
                    reglas[i].append("OPO_ATRASO_MAYOR_60D")
        ids.append(idc); periodos.append(per); trabs.append(trab); valores.append(val)

    r["id_cliente_norm"] = pd.array(ids, dtype="Int64")
    r["periodo_norm"] = periodos
    r["trabajadores_norm"] = pd.array(trabs, dtype="Int64")
    r["valor_norm"] = valores

    # --- Unicidad: sobre la llave normalizada (id + periodo)
    #   * Si en el grupo hay un solo registro que cumple todo lo demás, se conserva ese.
    #   * Varios buenos con valores idénticos -> se conserva el primero (duplicado exacto).
    #   * Varios buenos con valores distintos -> se rechazan todos (conflicto sin resolver).
    llave_ok = r["id_cliente_norm"].notna() & pd.Series([p is not None for p in periodos])
    evaluado["Unicidad"] = llave_ok.to_numpy()
    sin_otras = pd.Series([len(x) == 0 for x in reglas])
    grupos = r[llave_ok].groupby(["id_cliente_norm", "periodo_norm"], sort=False).groups
    for _, idx in grupos.items():
        if len(idx) < 2:
            continue
        buenos = [i for i in idx if sin_otras[i]]
        malos = [i for i in idx if not sin_otras[i]]
        for i in malos:
            advert[i].append("Llave duplicada en el archivo")
        if len(buenos) < 2:
            continue
        firmas = {(r.at[i, "trabajadores_norm"], r.at[i, "valor_norm"]) for i in buenos}
        if len(firmas) == 1:
            for i in buenos[1:]:
                reglas[i].append("UNI_DUPLICADO_EXACTO")
        else:
            for i in buenos:
                reglas[i].append("UNI_DUPLICADO_CONFLICTO")

    r["reglas"] = reglas
    r["advertencias"] = ["; ".join(a) for a in advert]
    r["valido"] = [len(x) == 0 for x in reglas]
    r["razon_rechazo"] = ["; ".join(REGLAS[c][1] for c in x) for x in reglas]
    r["reglas_incumplidas"] = [", ".join(x) for x in reglas]
    r.attrs["evaluado"] = evaluado
    return r


# ---------------------------------------------------------------------------
# 4. Reporte y exportación
# ---------------------------------------------------------------------------
def construir_reporte(r: pd.DataFrame, ruta_entrada: Path, cfg: Configuracion) -> dict:
    total = len(r)
    validos = int(r["valido"].sum())
    conteo_reglas = {cod: 0 for cod in REGLAS}
    for lista in r["reglas"]:
        for cod in lista:
            conteo_reglas[cod] += 1
    evaluado = r.attrs["evaluado"]
    por_dim = {}
    for dim in DIMENSIONES:
        ev = evaluado[dim]
        incumple = np.array([any(REGLAS[c][0] == dim for c in x) for x in r["reglas"]])
        n_ev = int(ev.sum())
        n_inc = int((incumple & ev).sum())
        por_dim[dim] = {
            "registros_evaluados": n_ev,
            "cumplen": n_ev - n_inc,
            "incumplen": n_inc,
            "score": round((n_ev - n_inc) / n_ev, 4) if n_ev else None,
        }
    score_global = round(validos / total, 4)
    return {
        "archivo": ruta_entrada.name,
        "sha256": hashlib.sha256(ruta_entrada.read_bytes()).hexdigest(),
        "fecha_ejecucion": datetime.now().isoformat(timespec="seconds"),
        "fecha_referencia": cfg.fecha_referencia.isoformat(),
        "total_registros": total,
        "registros_validos": validos,
        "registros_rechazados": total - validos,
        "score_global": score_global,
        "umbral_aprobacion": cfg.umbral_aprobacion,
        "estado_carga": "APROBADA" if score_global >= cfg.umbral_aprobacion else "RECHAZADA",
        "score_por_dimension": por_dim,
        "rechazados_por_regla": {
            cod: {"dimension": REGLAS[cod][0], "descripcion": REGLAS[cod][1], "registros": n}
            for cod, n in conteo_reglas.items()
        },
        "registros_con_advertencias": int((r["advertencias"] != "").sum()),
        "notas": [
            "Un registro puede incumplir varias reglas; por eso la suma por regla puede superar el total de rechazados.",
            "El score de cada dimensión se calcula sobre los registros en que esa dimensión era evaluable "
            "(p. ej. la oportunidad solo se evalúa si el periodo es legible).",
            f"Oportunidad: días de atraso contados desde el {'fin' if cfg.base_atraso == 'fin' else 'inicio'} "
            f"de mes del periodo hasta la fecha de referencia; máximo {MAX_DIAS_ATRASO} días.",
            "Formatos dd/mm/aaaa se interpretan con el día primero (convención colombiana).",
        ],
    }


def exportar(r: pd.DataFrame, reporte: dict, salida: Path) -> dict[str, Path]:
    salida.mkdir(parents=True, exist_ok=True)
    rutas = {"reporte": salida / "reporte_calidad.json",
             "validos": salida / "facturacion_validos.parquet",
             "rechazados": salida / "facturacion_rechazados.xlsx"}
    rutas["reporte"].write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")

    validos = r[r["valido"]].rename(columns={"id_cliente": "id_cliente_original", "periodo": "periodo_original"})
    validos = pd.DataFrame({
        "id_cliente": validos["id_cliente_norm"].astype("int64"),
        "periodo": pd.to_datetime(validos["periodo_norm"]),
        "trabajadores_activos": validos["trabajadores_norm"].astype("int64"),
        "valor_contrato": validos["valor_norm"].astype("float64"),
        "fila_origen": validos["fila_origen"],
        "advertencias": validos["advertencias"],
        "archivo_origen": reporte["archivo"],
        "fecha_validacion": reporte["fecha_ejecucion"],
    }).sort_values(["id_cliente", "periodo"])
    validos.to_parquet(rutas["validos"], index=False)

    rech = r[~r["valido"]][["fila_origen", *COLUMNAS, "razon_rechazo", "reglas_incumplidas", "advertencias"]]
    resumen = pd.DataFrame([
        {"regla": k, "dimension": v["dimension"], "descripcion": v["descripcion"], "registros": v["registros"]}
        for k, v in reporte["rechazados_por_regla"].items()])
    with pd.ExcelWriter(rutas["rechazados"], engine="openpyxl") as xw:
        rech.to_excel(xw, sheet_name="rechazados", index=False)
        resumen.to_excel(xw, sheet_name="resumen_por_regla", index=False)
        for hoja, ancho in [("rechazados", [11, 14, 14, 20, 16, 70, 45, 35]), ("resumen_por_regla", [26, 14, 70, 11])]:
            ws = xw.sheets[hoja]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for j, w in enumerate(ancho):
                ws.column_dimensions[chr(65 + j)].width = w
    return rutas


# ---------------------------------------------------------------------------
# 5. Orquestación
# ---------------------------------------------------------------------------
def ejecutar(entrada: Path, salida: Path, cfg: Configuracion) -> dict:
    df = cargar_archivo(entrada)
    LOG.info("Registros leídos: %d", len(df))
    r = validar(df, cfg)
    reporte = construir_reporte(r, entrada, cfg)
    rutas = exportar(r, reporte, salida)
    LOG.info("Válidos: %d | Rechazados: %d | Score global: %.1f%% -> carga %s",
             reporte["registros_validos"], reporte["registros_rechazados"],
             100 * reporte["score_global"], reporte["estado_carga"])
    for dim, v in reporte["score_por_dimension"].items():
        LOG.info("  %-13s %6.1f%%  (%d incumplen de %d evaluados)", dim, 100 * (v["score"] or 0),
                 v["incumplen"], v["registros_evaluados"])
    for nombre, ruta in rutas.items():
        LOG.info("Salida %-10s -> %s", nombre, ruta)
    return reporte


def parsear_args(argv=None):
    ap = argparse.ArgumentParser(description="Valida la calidad del archivo de facturación.")
    ap.add_argument("--entrada", type=Path, help="CSV/XLSX a validar. Si se omite, se genera uno de prueba.")
    ap.add_argument("--salida", type=Path, default=Path(__file__).parent / "salida")
    ap.add_argument("--clientes", type=int, default=600, help="Clientes del archivo de prueba (2 periodos c/u).")
    ap.add_argument("--fecha-referencia", type=date.fromisoformat, default=date.today(),
                    help="Fecha de la carga (AAAA-MM-DD). Por defecto, hoy.")
    ap.add_argument("--umbral", type=float, default=0.90, help="Score global mínimo para aprobar la carga.")
    ap.add_argument("--base-atraso", choices=["fin", "inicio"], default="fin",
                    help="Contar los 60 días desde el fin (defecto) o el inicio del mes del periodo.")
    ap.add_argument("--semilla", type=int, default=42)
    return ap.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    args = parsear_args(argv)
    cfg = Configuracion(args.fecha_referencia, args.umbral, args.base_atraso)
    try:
        entrada = args.entrada
        if entrada is None:
            entrada = args.salida / "facturacion_prueba.csv"
            generar_archivo_prueba(entrada, args.clientes, cfg.fecha_referencia, args.semilla)
        reporte = ejecutar(entrada, args.salida, cfg)
    except ErrorCarga as exc:
        LOG.error("Carga no procesada: %s", exc)
        return 1
    except Exception:                                   # error inesperado: se registra completo
        LOG.exception("Error inesperado durante la validación")
        return 1
    return 0 if reporte["estado_carga"] == "APROBADA" else 2


if __name__ == "__main__":
    sys.exit(main())
