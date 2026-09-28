"""
Generador de datos sintéticos para la prueba técnica.

Produce las 5 tablas del contexto del ejercicio (clientes, trabajadores, casos,
facturacion, prevencion) más una tabla de asignación de coordinadores que se usa
para la seguridad por filas (RLS) del modelo semántico de Power BI.

Los datos son 100 % sintéticos y reproducibles (semilla fija). Se usan en:
  - Sección 1 (Power BI): fuente de las tablas del modelo semántico.
  - Sección 2 (SQL): validación de las consultas sobre DuckDB.

Supuestos de negocio (documentados también en el README):
  - La tasa mensual de casos por cada 100 trabajadores crece con la clase de riesgo.
  - Los clientes con más actividades de prevención tienen, en promedio, menos casos.
  - casos.estado toma los valores 'abierto', 'cerrado' y 'anulado'. Los anulados son
    registros que no deben contarse como incidentes (supuesto explícito: el contexto
    no define el dominio de este campo).
  - 'grave' implica, en general, más de 15 días de ausencia, pero no siempre
    (hay casos graves de pocos días y leves que se complican), igual que en la realidad.

Fechas: la fecha de corte es siempre el día anterior a la ejecución (ayer) y la historia va desde el
1 de enero de dos años antes hasta ese corte. Así las consultas SQL, que también toman la fecha actual,
siempre encuentran datos del mes en curso, sin importar el día en que se ejecuten.

Uso:
    python datos/generar_datos.py              # genera CSV en datos/salida con corte = ayer
    python datos/generar_datos.py --salida X   # carpeta de salida alternativa
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 20260925
FECHA_CORTE = date.today() - timedelta(days=1)      # corte: el día anterior a la ejecución
FECHA_INICIO = date(FECHA_CORTE.year - 2, 1, 1)     # historia: desde el 1 de enero de dos años antes
N_CLIENTES = 120
N_COORDINADORES = 12

SECTORES = {
    # sector: (peso, clases de riesgo típicas)
    "Manufactura": (0.20, [3, 4, 5]),
    "Construcción": (0.13, [4, 5]),
    "Comercio": (0.15, [1, 2]),
    "Salud": (0.10, [2, 3]),
    "Transporte y logística": (0.12, [3, 4]),
    "Servicios profesionales": (0.12, [1, 2]),
    "Agroindustria": (0.10, [3, 4]),
    "Minería y energía": (0.08, [4, 5]),
}
# Tasa base mensual de casos por cada 100 trabajadores según clase de riesgo.
TASA_BASE_CLASE = {1: 0.35, 2: 0.8, 3: 1.5, 4: 2.5, 5: 3.6}
PROB_GRAVE_CLASE = {1: 0.08, 2: 0.12, 3: 0.18, 4: 0.24, 5: 0.30}
TIPOS_PREVENCION = [
    "Capacitación", "Inspección de seguridad", "Asesoría técnica",
    "Simulacro", "Evaluación de riesgos", "Pausas activas",
]
NOMBRES_BASE = [
    "Andina", "Pacífico", "Cordillera", "Horizonte", "Nogal", "Sabana", "Caribe",
    "Altamira", "Guadua", "Ceiba", "Magdalena", "Orinoco", "Tequendama", "Quimbaya",
    "Arrayán", "Samán", "Palmira", "Zenú", "Tayrona", "Farallones",
]
SUFIJOS = ["S.A.S.", "S.A.", "Ltda.", "& Cía.", "Group S.A.S."]
LOG = logging.getLogger("generar_datos")


def meses(inicio: date, fin: date) -> list[date]:
    """Primer día de cada mes entre inicio y fin (ambos incluidos)."""
    out, d = [], date(inicio.year, inicio.month, 1)
    while d <= fin:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def fin_de_mes(d: date) -> date:
    siguiente = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return siguiente - timedelta(days=1)


def sumar_meses(p: date, n: int) -> date:
    """Primer día del mes que está n meses antes (n < 0) o después de p."""
    total = p.year * 12 + p.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


def generar_clientes(rng: np.random.Generator) -> pd.DataFrame:
    sectores = list(SECTORES)
    pesos = np.array([SECTORES[s][0] for s in sectores])
    filas, usados = [], set()
    for i in range(1, N_CLIENTES + 1):
        sector = rng.choice(sectores, p=pesos / pesos.sum())
        clase = int(rng.choice(SECTORES[sector][1]))
        while True:
            nombre = f"{rng.choice(NOMBRES_BASE)} {sector.split()[0]} {rng.choice(SUFIJOS)}"
            if nombre not in usados:
                usados.add(nombre)
                break
            nombre = None
        # La mayoría de clientes tiene historia completa; algunos se vincularon en la ventana.
        if rng.random() < 0.8:
            vinc = date(FECHA_CORTE.year - 11, 1, 1) + timedelta(days=int(rng.integers(0, 3200)))
        else:
            vinc = FECHA_INICIO + timedelta(days=int(rng.integers(0, 850)))
        estado = "inactivo" if rng.random() < 0.08 else "activo"
        filas.append(dict(id_cliente=i, nombre=nombre, sector=sector, clase_riesgo=clase,
                          estado=estado, fecha_vinculacion=vinc))
    return pd.DataFrame(filas)


def generar_perfiles(rng: np.random.Generator, clientes: pd.DataFrame) -> pd.DataFrame:
    """Atributos latentes por cliente (no se exportan): tamaño, efecto de riesgo y prevención."""
    p = clientes[["id_cliente", "clase_riesgo", "estado", "fecha_vinculacion"]].copy()
    p["tamano"] = np.clip(rng.lognormal(mean=4.7, sigma=0.9, size=len(p)), 12, 2500).round().astype(int)
    p["efecto_cliente"] = rng.lognormal(mean=0.0, sigma=0.45, size=len(p))
    # Intensidad de prevención (actividades/mes). ~15 % de clientes casi no recibe prevención.
    p["intensidad_prev"] = np.where(rng.random(len(p)) < 0.15, 0.08, rng.uniform(0.6, 3.2, len(p)))
    p["crecimiento"] = rng.normal(0.004, 0.01, len(p))           # crecimiento mensual de planta
    # Los inactivos dejan de facturar en algún mes de hace 9 a 18 meses (relativo al corte)
    p["mes_retiro"] = [
        sumar_meses(date(FECHA_CORTE.year, FECHA_CORTE.month, 1), -int(rng.integers(9, 19))) if e == "inactivo" else None
        for e in p["estado"]
    ]
    return p


def generar_facturacion(rng, perfiles) -> pd.DataFrame:
    filas = []
    tarifa_clase = {1: 38_000, 2: 52_000, 3: 71_000, 4: 96_000, 5: 128_000}
    for _, c in perfiles.iterrows():
        inicio = max(FECHA_INICIO, date(c.fecha_vinculacion.year, c.fecha_vinculacion.month, 1))
        for k, m in enumerate(meses(inicio, FECHA_CORTE)):
            if c.mes_retiro and m >= c.mes_retiro:
                break
            trab = max(5, int(round(c.tamano * (1 + c.crecimiento) ** k * rng.normal(1, 0.03))))
            valor = round(trab * tarifa_clase[c.clase_riesgo] * rng.normal(1, 0.02), -3)
            filas.append(dict(id_cliente=c.id_cliente, periodo=m, trabajadores_activos=trab,
                              valor_contrato=valor))
    return pd.DataFrame(filas)


def generar_trabajadores(rng, facturacion) -> pd.DataFrame:
    """Plantilla por cliente: tantos trabajadores como el máximo facturado (con rotación)."""
    filas, idt = [], 1
    maximos = facturacion.groupby("id_cliente")["trabajadores_activos"].max()
    ultimos = facturacion.sort_values("periodo").groupby("id_cliente")["trabajadores_activos"].last()
    for idc, n_max in maximos.items():
        n_activos = ultimos[idc]
        for j in range(int(n_max * 1.12)):          # 12 % adicional de retirados (rotación)
            ingreso = date(FECHA_CORTE.year - 10, 1, 1) + timedelta(days=int(rng.integers(0, 3700)))
            estado = "activo" if j < n_activos else "retirado"
            filas.append(dict(id_trabajador=idt, id_cliente=idc,
                              nombre=f"Trabajador {idt:06d}", fecha_ingreso=min(ingreso, FECHA_CORTE),
                              estado=estado))
            idt += 1
    return pd.DataFrame(filas)


def generar_prevencion(rng, perfiles, facturacion) -> pd.DataFrame:
    filas, ida = [], 1
    periodos = facturacion.groupby("id_cliente")["periodo"].agg(["min", "max"])
    for _, c in perfiles.iterrows():
        if c.id_cliente not in periodos.index:
            continue
        pmin, pmax = periodos.loc[c.id_cliente]
        for m in meses(pmin, pmax):
            # Algunos clientes con poca prevención llevan meses sin ninguna actividad reciente.
            n = rng.poisson(c.intensidad_prev)
            ultimo_dia = min(fin_de_mes(m), FECHA_CORTE)
            for _ in range(n):
                f = m + timedelta(days=int(rng.integers(0, (ultimo_dia - m).days + 1)))
                tipo = rng.choice(TIPOS_PREVENCION)
                part = int(np.clip(rng.normal(22, 10), 3, 80))
                filas.append(dict(id_actividad=ida, id_cliente=c.id_cliente, fecha=f,
                                  tipo=tipo, participantes=part))
                ida += 1
    return pd.DataFrame(filas)


def generar_casos(rng, perfiles, facturacion, prevencion, trabajadores) -> pd.DataFrame:
    """Casos mensuales ~ Poisson(tasa * trabajadores/100), con estacionalidad y efecto prevención."""
    prev_mes = (prevencion.assign(periodo=pd.to_datetime(prevencion["fecha"]).dt.to_period("M"))
                .groupby(["id_cliente", "periodo"]).size())
    trab_por_cliente = trabajadores.groupby("id_cliente")["id_trabajador"].apply(np.array)
    perf = perfiles.set_index("id_cliente")
    estacional = {1: 0.9, 2: 0.95, 3: 1.05, 4: 1.0, 5: 1.05, 6: 1.0, 7: 1.1,
                  8: 1.1, 9: 1.05, 10: 1.0, 11: 0.95, 12: 0.8}
    filas, idc = [], 1
    for f in facturacion.itertuples():
        c = perf.loc[f.id_cliente]
        m = f.periodo
        prev_ult3 = sum(prev_mes.get((f.id_cliente, pd.Period(m, "M") - k), 0) for k in range(1, 4))
        efecto_prev = 1.0 / (1 + 0.12 * prev_ult3)             # más prevención, menos casos
        tendencia = 1 - 0.004 * ((m.year - 2024) * 12 + m.month)  # leve mejora en el tiempo
        tasa = TASA_BASE_CLASE[c.clase_riesgo] * c.efecto_cliente * efecto_prev * \
            estacional[m.month] * tendencia * 1.35
        ultimo_dia = min(fin_de_mes(m), FECHA_CORTE)
        fraccion_mes = ((ultimo_dia - m).days + 1) / ((fin_de_mes(m) - m).days + 1)
        n = rng.poisson(max(tasa, 0) * f.trabajadores_activos / 100 * fraccion_mes)
        for _ in range(n):
            fecha = m + timedelta(days=int(rng.integers(0, (ultimo_dia - m).days + 1)))
            grave = rng.random() < PROB_GRAVE_CLASE[c.clase_riesgo]
            if grave:
                # La mayoría de graves supera 15 días; ~10 % son graves de pocos días
                dias = int(rng.integers(3, 15)) if rng.random() < 0.10 else int(rng.gamma(2.2, 22) + 16)
                costo = dias * rng.uniform(260_000, 420_000) + rng.uniform(1.5e6, 9e6)
            else:
                # ~4 % de leves se complican y superan 15 días
                dias = int(rng.integers(16, 30)) if rng.random() < 0.04 else int(rng.integers(0, 12))
                costo = dias * rng.uniform(150_000, 260_000) + rng.uniform(80_000, 700_000)
            antig = (FECHA_CORTE - fecha).days
            if rng.random() < 0.03:
                estado = "anulado"
            elif antig < 45 or (grave and antig < 120 and rng.random() < 0.5):
                estado = "abierto"
            else:
                estado = "cerrado"
            filas.append(dict(id_caso=idc, id_cliente=f.id_cliente,
                              id_trabajador=int(rng.choice(trab_por_cliente[f.id_cliente])),
                              fecha_ocurrencia=fecha, tipo="grave" if grave else "leve",
                              dias_ausencia=dias, costo=round(costo, -3), estado=estado))
            idc += 1
    return pd.DataFrame(filas)


def generar_asignaciones(rng, clientes) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coordinadores ficticios y su cartera de clientes (tabla de seguridad para RLS)."""
    coords = pd.DataFrame({
        "id_coordinador": range(1, N_COORDINADORES + 1),
        "nombre_coordinador": [f"Coordinador {i:02d}" for i in range(1, N_COORDINADORES + 1)],
        "correo": [f"coordinador{i:02d}@empresa-ejemplo.co" for i in range(1, N_COORDINADORES + 1)],
        "regional": [["Antioquia", "Bogotá", "Valle", "Caribe"][i % 4] for i in range(N_COORDINADORES)],
    })
    asign = pd.DataFrame({
        "id_cliente": clientes["id_cliente"],
        "id_coordinador": rng.integers(1, N_COORDINADORES + 1, len(clientes)),
    })
    asign = asign.merge(coords[["id_coordinador", "correo"]], on="id_coordinador")
    asign["vigente_desde"] = date(FECHA_CORTE.year, 1, 1)
    return coords, asign.sort_values("id_cliente")[["id_cliente", "id_coordinador", "correo", "vigente_desde"]]


def generar_todo(salida: Path) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(SEMILLA)
    clientes = generar_clientes(rng)
    perfiles = generar_perfiles(rng, clientes)
    facturacion = generar_facturacion(rng, perfiles)
    trabajadores = generar_trabajadores(rng, facturacion)
    prevencion = generar_prevencion(rng, perfiles, facturacion)
    casos = generar_casos(rng, perfiles, facturacion, prevencion, trabajadores)
    coordinadores, asignaciones = generar_asignaciones(rng, clientes)
    tablas = dict(clientes=clientes, trabajadores=trabajadores, casos=casos,
                  facturacion=facturacion, prevencion=prevencion,
                  coordinadores=coordinadores, asignacion_coordinador=asignaciones)
    salida.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        df.to_csv(salida / f"{nombre}.csv", index=False, encoding="utf-8")
        LOG.info("%-24s %7d filas", nombre, len(df))
    (salida / "fecha_corte.txt").write_text(FECHA_CORTE.isoformat(), encoding="utf-8")
    return tablas


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path(__file__).parent / "salida")
    args = ap.parse_args()
    generar_todo(args.salida)
    LOG.info("Datos generados en %s (fecha de corte %s)", args.salida.resolve(), FECHA_CORTE)


if __name__ == "__main__":
    main()
