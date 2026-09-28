"""
Obtención y agregación de datos para el análisis.

Se lee UNA vez el grano cliente × mes (unos pocos miles de filas) de los clientes que el usuario puede
ver y con los filtros aplicados, y todos los análisis se calculan en memoria sobre ese "cubo".
El alcance por usuario reutiliza tablero.servicios.indicadores.clientes_visibles (mismo control que el tablero).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from apps.tablero.models import CargaDatos, ConfiguracionTablero, IndicadorMensual
from apps.tablero.servicios.indicadores import Filtros, clientes_visibles

OPCIONALES = {  # variable -> campo del modelo que la contiene
    "dias": "dias_ausencia", "abiertos": "casos_abiertos", "prevencion": "actividades_prevencion",
    "valor": "valor_contrato",
}


@dataclass
class InfoCliente:
    id: int
    nombre: str
    sector_id: int
    sector: str
    clase: int
    coordinador_id: int | None
    coordinador: str
    regional: str
    activo: bool


@dataclass
class Fila:
    cliente: int
    periodo: date
    trab: int
    casos: int
    graves: int
    costo_leve: float
    costo_grave: float
    dias: int | None
    abiertos: int | None
    graves_abiertos: int | None
    prev: int | None
    participantes: int | None
    valor: float | None

    @property
    def costo(self):
        return self.costo_leve + self.costo_grave


@dataclass
class Agregado:
    """Sumas base de un conjunto de filas. Los indicadores se calculan a partir de aquí (kpis.py)."""

    casos: int = 0
    graves: int = 0
    costo: float = 0.0
    costo_grave: float = 0.0
    trab: int = 0
    dias: int | None = 0
    abiertos: int | None = 0
    graves_abiertos: int | None = 0
    prev: int | None = 0
    valor: float | None = 0.0
    clientes: int = 0
    clientes_con_prev: int | None = 0
    criticos: int = 0
    trab_criticos: int = 0
    meses: int = 0


@dataclass
class Cubo:
    filas: list[Fila]
    clientes: dict[int, InfoCliente]
    periodos: list[date]                         # periodos disponibles (todos los meses cerrados cargados)
    variables: set[str]
    carga: CargaDatos | None
    umbral_critico: float
    umbral_moderado: float
    por_periodo: dict[date, list[Fila]] = field(default_factory=dict)

    def __post_init__(self):
        g = defaultdict(list)
        for f in self.filas:
            g[f.periodo].append(f)
        self.por_periodo = dict(g)

    def tiene(self, variable: str) -> bool:
        return variable in self.variables


def obtener_cubo(usuario, filtros: Filtros, hasta: date | None = None) -> Cubo:
    cfg = ConfiguracionTablero.actual()
    visibles = clientes_visibles(usuario).filter(clase_riesgo__in=filtros.clases)
    if filtros.coordinador_id:
        visibles = visibles.filter(coordinador_id=filtros.coordinador_id)
    if filtros.sector_id:
        visibles = visibles.filter(sector_id=filtros.sector_id)
    clientes = {
        c.id: InfoCliente(c.id, c.nombre, c.sector_id, c.sector.nombre, c.clase_riesgo, c.coordinador_id,
                          c.coordinador.nombre if c.coordinador else "Sin coordinador",
                          (c.coordinador.regional or "Sin regional") if c.coordinador else "Sin regional", c.activo)
        for c in visibles.select_related("sector", "coordinador")
    }
    qs = IndicadorMensual.objects.filter(cliente_id__in=clientes.keys())
    if hasta:
        qs = qs.filter(periodo__lte=hasta)
    campos = ["cliente_id", "periodo", "trabajadores_activos", "casos", "casos_graves", "costo_leve", "costo_grave",
              "dias_ausencia", "casos_abiertos", "casos_graves_abiertos", "actividades_prevencion",
              "participantes_prevencion", "valor_contrato"]
    filas = []
    presentes = {k: True for k in OPCIONALES}
    for r in qs.values_list(*campos).iterator(chunk_size=2000):
        f = Fila(r[0], r[1], r[2], r[3], r[4], float(r[5]), float(r[6]), r[7], r[8], r[9], r[10], r[11],
                 float(r[12]) if r[12] is not None else None)
        for var, attr in (("dias", f.dias), ("abiertos", f.abiertos), ("prevencion", f.prev), ("valor", f.valor)):
            if attr is None:
                presentes[var] = False
        filas.append(f)
    variables = {v for v, ok in presentes.items() if ok} if filas else set()
    periodos = sorted(IndicadorMensual.objects.values_list("periodo", flat=True).distinct())
    return Cubo(filas, clientes, periodos, variables, CargaDatos.vigente(), float(cfg.umbral_critico),
                float(cfg.umbral_moderado))


def agregar(filas: list[Fila], cubo: Cubo, meses: int = 1) -> Agregado:
    a = Agregado(meses=meses)
    tiene_dias, tiene_prev, tiene_valor, tiene_ab = (cubo.tiene("dias"), cubo.tiene("prevencion"),
                                                     cubo.tiene("valor"), cubo.tiene("abiertos"))
    for f in filas:
        a.casos += f.casos
        a.graves += f.graves
        a.costo += f.costo
        a.costo_grave += f.costo_grave
        a.trab += f.trab
        a.clientes += 1
        if tiene_dias:
            a.dias += f.dias
        if tiene_ab:
            a.abiertos += f.abiertos
            a.graves_abiertos += f.graves_abiertos
        if tiene_prev:
            a.prev += f.prev
            a.clientes_con_prev += 1 if f.prev > 0 else 0
        if tiene_valor:
            a.valor += f.valor
        if f.trab and f.casos / f.trab * 100 > cubo.umbral_critico:
            a.criticos += 1
            a.trab_criticos += f.trab
    if not tiene_dias:
        a.dias = None
    if not tiene_ab:
        a.abiertos = a.graves_abiertos = None
    if not tiene_prev:
        a.prev = a.clientes_con_prev = None
    if not tiene_valor:
        a.valor = None
    return a


def filas_en(cubo: Cubo, periodos) -> list[Fila]:
    salida = []
    for p in periodos:
        salida.extend(cubo.por_periodo.get(p, []))
    return salida


def desplazar(p: date, meses: int) -> date:
    total = p.year * 12 + p.month - 1 + meses
    return date(total // 12, total % 12 + 1, 1)


def ventana(p: date, n: int) -> list[date]:
    """Los n meses que terminan en p (incluido)."""
    return [desplazar(p, -i) for i in range(n - 1, -1, -1)]
