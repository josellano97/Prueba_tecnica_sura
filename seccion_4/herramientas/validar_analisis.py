"""
Validación independiente de la capa analítica (herramienta de desarrollo, requiere pandas).

Recalcula con pandas, directamente desde los CSV de datos/salida y SIN usar el código de la aplicación,
las cifras que muestra el análisis gerencial, y las compara con el resultado del motor.

    pip install -r requirements-dev.txt
    python manage.py cargar_datos_proyecto
    python herramientas/validar_analisis.py
"""
import math
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django  # noqa: E402

django.setup()
from django.contrib.auth import get_user_model  # noqa: E402

from apps.analisis.servicios import motor  # noqa: E402
from apps.tablero.servicios.indicadores import Filtros  # noqa: E402

DATOS = RAIZ.parent / "datos" / "salida"
# último mes cerrado: el anterior al mes de la fecha de corte de los datos (corte = ayer)
CORTE = pd.Timestamp((DATOS / "fecha_corte.txt").read_text(encoding="utf-8").strip())
MES = CORTE.replace(day=1) - pd.DateOffset(months=1)
resultados = []


def check(nombre, esperado, obtenido, tol=1e-9):
    ok = (esperado == obtenido) if isinstance(esperado, (int, str)) else abs(esperado - obtenido) <= tol * max(1, abs(esperado))
    resultados.append(ok)
    print(f"  [{'OK' if ok else 'FALLA'}] {nombre}: pandas={esperado!r:<22} app={obtenido!r}")


def poisson_superior(k, lam):          # implementación distinta a la de la app (recursión de la fdp)
    pmf, acumulada = math.exp(-lam), 0.0
    for i in range(k):
        acumulada += pmf
        pmf *= lam / (i + 1)
    return 1 - acumulada


# ---------------------------------------------------------------- recálculo con pandas
c = pd.read_csv(DATOS / "casos.csv", parse_dates=["fecha_ocurrencia"])
f = pd.read_csv(DATOS / "facturacion.csv", parse_dates=["periodo"])
p = pd.read_csv(DATOS / "prevencion.csv", parse_dates=["fecha"])
cl = pd.read_csv(DATOS / "clientes.csv")
c = c[c.estado != "anulado"].assign(periodo=lambda d: d.fecha_ocurrencia.dt.to_period("M").dt.to_timestamp())
p = p.assign(periodo=lambda d: d.fecha.dt.to_period("M").dt.to_timestamp())
cm = c.groupby(["id_cliente", "periodo"]).agg(casos=("id_caso", "size"), graves=("tipo", lambda s: (s == "grave").sum()),
                                              costo=("costo", "sum"), dias=("dias_ausencia", "sum")).reset_index()
pm = p.groupby(["id_cliente", "periodo"]).size().rename("prev").reset_index()
g = f.merge(cm, on=["id_cliente", "periodo"], how="left").merge(pm, on=["id_cliente", "periodo"], how="left").fillna(0)
g = g.merge(cl[["id_cliente", "sector", "clase_riesgo"]], on="id_cliente")
g = g[g.periodo <= MES]


def mes(d):
    return g[g.periodo == d]


a = mes(MES)
tasa = a.casos.sum() / a.trabajadores_activos.sum() * 100
prev12 = g[(g.periodo >= MES - pd.DateOffset(months=12)) & (g.periodo < MES)]
tasa12 = prev12.casos.sum() / prev12.trabajadores_activos.sum() * 100
jul, ago25 = mes(MES - pd.DateOffset(months=1)), mes(MES - pd.DateOffset(months=12))
ytd = g[(g.periodo.dt.year == MES.year)]
ytd_ant = g[(g.periodo.dt.year == MES.year - 1) & (g.periodo.dt.month <= MES.month)]
criticos = int((a.casos / a.trabajadores_activos * 100 > 5).sum())
doce = g[g.periodo > MES - pd.DateOffset(months=12)]
costo_cli = doce.groupby("id_cliente").costo.sum().sort_values(ascending=False)
n80 = int((costo_cli.cumsum() / costo_cli.sum() < 0.8).sum() + 1)
tasa_clase = doce.groupby("clase_riesgo").casos.sum() / doce.groupby("clase_riesgo").trabajadores_activos.sum()
doce = doce.assign(esp=doce.trabajadores_activos * doce.clase_riesgo.map(tasa_clase))
sir = (doce.groupby("sector").casos.sum() / doce.groupby("sector").esp.sum())

# ---------------------------------------------------------------- resultado de la app
superusuario = get_user_model()(is_superuser=True, is_active=True)
r = motor._calcular(superusuario, Filtros(mes=MES.date()))
k = r["kpis"]
print(f"== Indicadores de nivel 1, {MES:%m/%Y} (último mes cerrado; corte de los datos {CORTE:%d/%m/%Y})")
check("casos", int(a.casos.sum()), k["casos"]["valor"])
check("trabajadores", int(a.trabajadores_activos.sum()), k["trabajadores"]["valor"])
check("tasa", tasa, k["tasa"]["valor"])
check("costo", float(a.costo.sum()), k["costo"]["valor"], 1e-6)
check("días perdidos x 100", a.dias.sum() / a.trabajadores_activos.sum() * 100, k["severidad"]["valor"])
check("cobertura de prevención", (a.prev > 0).mean(), k["cobertura_prevencion"]["valor"])
check("clientes críticos", criticos, k["criticos"]["valor"])
print("== Comparaciones")
check("tasa mes anterior", jul.casos.sum() / jul.trabajadores_activos.sum() * 100, k["tasa"]["referencias"]["mes_anterior"]["valor"])
check("tasa mismo mes año anterior", ago25.casos.sum() / ago25.trabajadores_activos.sum() * 100, k["tasa"]["referencias"]["anio_anterior"]["valor"])
check("tasa 12 meses previos (ponderada)", tasa12, k["tasa"]["referencias"]["promedio_12m"]["valor"])
check("tasa año corrido", ytd.casos.sum() / ytd.trabajadores_activos.sum() * 100, k["tasa"]["ytd"]["valor"])
check("tasa año corrido año anterior", ytd_ant.casos.sum() / ytd_ant.trabajadores_activos.sum() * 100, k["tasa"]["ytd"]["anterior"])
print("== Concentración y análisis")
check("clientes que explican el 80 % del costo", n80, r["pareto_costo"]["n_corte"])
for s in r["sobre_sector"]:
    check(f"razón estandarizada {s['nombre']}", float(sir[s["nombre"]]), s["ajustado"], 1e-9)
for s_app in r["anomalias"]["sectores"][:1]:        # el sector más anómalo del mes, si lo hay
    tl = a[a.sector == s_app["nombre"]]
    b = prev12[prev12.sector == s_app["nombre"]]
    esperado_tl = tl.trabajadores_activos.sum() * b.casos.sum() / b.trabajadores_activos.sum()
    check(f"{s_app['nombre']}: casos esperables", esperado_tl, s_app["esperado"], 1e-9)
    check(f"{s_app['nombre']}: p-valor Poisson (otra implementación)", poisson_superior(int(tl.casos.sum()), esperado_tl), s_app["p"], 1e-6)
d = r["descomposicion_mes"]
check("descomposición casos suma la variación", float(d["casos"]["total"]), d["casos"]["exposicion"] + d["casos"]["riesgo"], 1e-9)
check("descomposición tasa suma la variación", d["tasa"]["total"], d["tasa"]["mezcla"] + d["tasa"]["intra"], 1e-9)
print(f"\nResumen: {sum(resultados)}/{len(resultados)} verificaciones OK")
sys.exit(0 if all(resultados) else 1)
