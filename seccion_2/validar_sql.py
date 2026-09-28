"""
Ejecuta y valida las consultas de la Sección 2 sobre DuckDB con los datos sintéticos.

Para cada consulta:
  1. La ejecuta sobre las tablas del contexto (cargadas desde datos/salida/*.csv).
  2. Recalcula los mismos indicadores de forma independiente con pandas.
  3. Compara ambos resultados y reporta OK / FALLA.
  4. Guarda el resultado en seccion_2/resultados/*.csv para revisión.

Uso:
    python seccion_2/validar_sql.py
Código de salida 0 si todas las validaciones pasan, 1 si alguna falla.
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta  # noqa: F401
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ.parent / "datos" / "salida"
SALIDA = RAIZ / "resultados"
# Las consultas toman la fecha actual (corte = ayer); la validación usa exactamente la misma fecha.
HOY = pd.Timestamp(date.today())
FECHA_CORTE = HOY - pd.Timedelta(days=1)
INI_MES = FECHA_CORTE.replace(day=1)                     # mes en curso
INI_MES_ANT = INI_MES - pd.DateOffset(months=1)          # mes anterior
FIN_MES_ANT = INI_MES - pd.Timedelta(days=1)
INI_12_PERIODOS = INI_MES - pd.DateOffset(months=11)     # 12 periodos de facturación
TABLAS = ["clientes", "trabajadores", "casos", "facturacion", "prevencion"]
resultados: list[tuple[str, bool, str]] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    resultados.append((nombre, bool(condicion), detalle))
    print(f"  [{'OK' if condicion else 'FALLA'}] {nombre} {detalle}")


def conectar() -> duckdb.DuckDBPyConnection:
    if not (DATOS / "casos.csv").exists():
        sys.exit(f"No se encontraron datos en {DATOS}. Ejecute primero: python datos/generar_datos.py")
    corte_datos = (DATOS / "fecha_corte.txt").read_text(encoding="utf-8").strip()
    if corte_datos != FECHA_CORTE.date().isoformat():
        print(f"AVISO: los datos tienen corte {corte_datos}, pero las consultas usan {FECHA_CORTE.date()} (ayer). "
              "Regenere los datos con: python datos/generar_datos.py")
    con = duckdb.connect()
    for t in TABLAS:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{(DATOS / (t + '.csv')).as_posix()}')")
    return con


def leer_sql(nombre: str) -> str:
    return (RAIZ / nombre).read_text(encoding="utf-8")


def pandas_base() -> dict[str, pd.DataFrame]:
    d = {t: pd.read_csv(DATOS / f"{t}.csv") for t in TABLAS}
    d["casos"]["fecha_ocurrencia"] = pd.to_datetime(d["casos"]["fecha_ocurrencia"])
    d["facturacion"]["periodo"] = pd.to_datetime(d["facturacion"]["periodo"])
    d["prevencion"]["fecha"] = pd.to_datetime(d["prevencion"]["fecha"])
    return d


def validar_2_1(con, d) -> None:
    print("\n== 2.1 Consulta heredada vs corregida")
    original = leer_sql("2_1_consulta_original.sql")
    original = re.sub(r"DATEADD\(month,\s*-(\d+),\s*CURRENT_DATE\)",
                      r"(CURRENT_DATE - INTERVAL \1 MONTH)", original)
    orig = con.execute(original).df()
    corr = con.execute(leer_sql("2_1_consulta_corregida.sql")).df()
    orig.to_csv(SALIDA / "2_1_resultado_original.csv", index=False)
    corr.to_csv(SALIDA / "2_1_resultado_corregido.csv", index=False)

    # (a) Cuantificar el fan-out: casos reales con los MISMOS filtros de la consulta original
    ca, cl, fa = d["casos"], d["clientes"], d["facturacion"]
    ref = HOY                                   # la consulta original usa CURRENT_DATE (hoy)
    reales = ca[ca.fecha_ocurrencia >= ref - pd.DateOffset(months=12)].groupby("id_cliente").size()
    filas_fact = fa[fa.periodo >= ref - pd.DateOffset(months=6)].groupby("id_cliente").size()
    m = orig.set_index("id_cliente").join(reales.rename("reales")).join(filas_fact.rename("filas_fact"))
    m["factor"] = m.total_casos / m.reales
    check("fan-out: total_casos original = casos reales x filas de facturación",
          bool((m.total_casos == m.reales * m.filas_fact.fillna(1)).all()),
          f"(factor medio de inflación {m.factor.mean():.2f}x; total original {int(m.total_casos.sum())} "
          f"vs real {int(m.reales.sum())})")

    # (b) La consulta corregida coincide con un cálculo independiente
    desde = FECHA_CORTE - pd.DateOffset(months=12)
    v = ca[(ca.fecha_ocurrencia > desde) & (ca.fecha_ocurrencia <= FECHA_CORTE) & (ca.estado != "anulado")]
    act = cl[cl.estado == "activo"].id_cliente
    esp = v[v.id_cliente.isin(act)].groupby("id_cliente").agg(
        total_casos=("id_caso", "size"), casos_graves=("tipo", lambda s: (s == "grave").sum()),
        costo_total=("costo", "sum"))
    per = fa[(fa.periodo >= INI_12_PERIODOS) & (fa.periodo <= FECHA_CORTE)]
    esp = esp.join(per.groupby("id_cliente").trabajadores_activos.mean().rename("trab"))
    c2 = corr.set_index("id_cliente").sort_index()
    esp = esp.sort_index()
    check("corregida: mismo conjunto de clientes", list(c2.index) == list(esp.index), f"({len(c2)} clientes)")
    check("corregida: total_casos, graves y costo cuadran",
          np.allclose(c2[["total_casos", "casos_graves", "costo_total"]].values,
                      esp[["total_casos", "casos_graves", "costo_total"]].values))
    check("corregida: costo_x_trab cuadra",
          np.allclose(c2.costo_x_trab.values, (esp.costo_total / esp.trab).round(0).values, atol=1))
    dif_graves = (v.tipo.eq("grave") != v.dias_ausencia.gt(15)).sum()
    check("hallazgo: 'dias_ausencia > 15' no equivale a tipo = 'grave'", dif_graves > 0,
          f"({dif_graves} casos clasificados distinto en la ventana)")


def validar_2_2(con, d) -> None:
    print("\n== 2.2 Top 15 atención prioritaria")
    top = con.execute(leer_sql("2_2_top15_atencion_prioritaria.sql")).df()
    top.to_csv(SALIDA / "2_2_top15.csv", index=False)
    cl = d["clientes"].set_index("id_cliente")
    check("devuelve exactamente 15 clientes", len(top) == 15)
    check("sin clientes repetidos", top.id_cliente.is_unique)
    check("solo clientes activos", bool((cl.loc[top.id_cliente, "estado"] == "activo").all()))
    check("ordenado por puntaje descendente", top.puntaje_prioridad.is_monotonic_decreasing)
    check("puntaje en rango 0-100", top.puntaje_prioridad.between(0, 100).all())
    # recalcular casos_90d de forma independiente
    ca = d["casos"]
    v = ca[(ca.estado != "anulado") & (ca.fecha_ocurrencia > FECHA_CORTE - pd.Timedelta(days=90))
           & (ca.fecha_ocurrencia <= FECHA_CORTE)].groupby("id_cliente").size()
    check("casos_90d cuadra con cálculo independiente",
          bool((top.set_index("id_cliente").casos_90d == v.reindex(top.id_cliente).fillna(0).values).all()))
    print(top[["prioridad", "nombre", "clase_riesgo", "puntaje_prioridad", "tasa_ajustada",
               "casos_90d", "graves_abiertos", "dias_sin_prevencion", "motivo_principal"]].to_string(index=False))


def validar_2_3(con, d) -> None:
    print("\n== 2.3 Pipeline diario + controles de calidad")
    res = con.execute(leer_sql("2_3_pipeline_diario.sql")).df()
    res.to_csv(SALIDA / "2_3_resultado_pipeline.csv", index=False)
    con.register("resultado_df", res)
    con.execute("CREATE TABLE resultado_pipeline AS SELECT * FROM resultado_df")

    ca, cl, fa, pr = d["casos"], d["clientes"], d["facturacion"], d["prevencion"]
    act = cl[cl.estado == "activo"].id_cliente
    v = ca[ca.estado != "anulado"]
    mes = v[(v.fecha_ocurrencia >= INI_MES) & (v.fecha_ocurrencia <= FECHA_CORTE)].groupby("id_cliente").size()
    ant = v[(v.fecha_ocurrencia >= INI_MES_ANT) & (v.fecha_ocurrencia <= FIN_MES_ANT)].groupby("id_cliente").size()
    trab = fa[fa.periodo == INI_MES].set_index("id_cliente").trabajadores_activos
    prev = pr[(pr.fecha > FECHA_CORTE - pd.Timedelta(days=30)) & (pr.fecha <= FECHA_CORTE)].groupby("id_cliente").size()
    r = res.set_index("id_cliente").sort_index()
    idx = r.index
    check("1 fila por cliente activo", len(r) == len(act) and set(idx) == set(act), f"({len(r)} filas)")
    check("casos_mes cuadra", bool((r.casos_mes == mes.reindex(idx).fillna(0)).all()))
    check("casos_mes_anterior cuadra", bool((r.casos_mes_anterior == ant.reindex(idx).fillna(0)).all()))
    tasa = (mes.reindex(idx).fillna(0) / trab.reindex(idx) * 100).round(2)
    check("tasa_incidencia cuadra", np.allclose(r.tasa_incidencia, tasa, equal_nan=True))
    check("prevención 30 d cuadra", bool((r.actividades_prevencion_30d == prev.reindex(idx).fillna(0)).all()))
    clas = np.where(tasa.isna(), "sin dato", np.where(tasa > 5, "crítico", np.where(tasa >= 2, "moderado", "bajo")))
    check("clasificación cuadra", bool((r.clasificacion.values == clas).all()),
          f"({pd.Series(clas).value_counts().to_dict()})")

    ctrl = con.execute(leer_sql("2_3_controles_calidad.sql")).df()
    ctrl.to_csv(SALIDA / "2_3_controles_calidad.csv", index=False)
    print(ctrl[["control", "severidad", "valor", "umbral", "resultado"]].to_string(index=False))
    bloq = ctrl[(ctrl.severidad == "bloqueante") & (ctrl.resultado == "FALLA")]
    check("controles bloqueantes en OK con datos sanos", bloq.empty, "" if bloq.empty else str(list(bloq.control)))

    # Prueba negativa: si la carga de casos llega incompleta, los controles deben bloquear
    con.execute("CREATE TABLE casos_backup AS SELECT * FROM casos")
    con.execute("DELETE FROM casos WHERE fecha_ocurrencia >= CURRENT_DATE - INTERVAL 5 DAY")
    con.execute("INSERT INTO casos SELECT * FROM casos WHERE id_caso < 50")        # duplicados
    ctrl_mala = con.execute(leer_sql("2_3_controles_calidad.sql")).df()
    fallas = set(ctrl_mala[ctrl_mala.resultado == "FALLA"].control)
    check("prueba negativa: carga incompleta y duplicada es detectada",
          {"frescura_casos", "duplicados_id_caso", "conciliacion_casos_mes"} <= fallas, f"({sorted(fallas)})")
    con.execute("DROP TABLE casos; ALTER TABLE casos_backup RENAME TO casos")


def main() -> int:
    SALIDA.mkdir(exist_ok=True)
    print(f"Fecha de corte (ayer): {FECHA_CORTE.date()}")
    con, d = conectar(), pandas_base()
    validar_2_1(con, d)
    validar_2_2(con, d)
    validar_2_3(con, d)
    fallas = [r for r in resultados if not r[1]]
    print(f"\nResumen: {len(resultados) - len(fallas)}/{len(resultados)} validaciones OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
