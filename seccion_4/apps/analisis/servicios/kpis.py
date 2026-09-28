"""
Catálogo de indicadores: una sola definición por KPI (cálculo + explicación + limitaciones).

agregacion:
  'suma'              conteos/montos: en una ventana se reporta el promedio mensual (total / meses)
  'razon'             tasas: se calcula sobre la ventana completa (suma de numeradores / suma de denominadores),
                      nunca como promedio de tasas mensuales (daría más peso a los clientes pequeños)
  'promedio_mensual'  niveles que no se suman entre meses (p. ej. clientes críticos)
sentido: 'baja' = menor es mejor · 'sube' = mayor es mejor · 'neutro' = descriptivo, sin juicio de valor.

No se define ninguna meta: la fuente no la trae. La única regla oficial es la clasificación
crítico / moderado / bajo por tasa (pregunta 2.3 de la prueba), con umbrales configurables.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .datos import Agregado


@dataclass(frozen=True)
class KPI:
    clave: str
    nombre: str
    nivel: int
    unidad: str
    formato: str                   # 'entero' | 'decimal2' | 'pct1' | 'cop' | 'decimal1'
    sentido: str
    agregacion: str
    formula: str
    fuente: str
    interpretacion: str
    limitaciones: str
    requiere: str | None
    calculo: Callable[[Agregado], float | None]
    comparable: bool = True        # False = foto a la fecha de corte: no se compara entre periodos

    def __reduce__(self):            # se serializa por su clave (la caché no puede guardar funciones)
        return (por_clave, (self.clave,))

    def valor(self, a: Agregado | None):
        if a is None:
            return None
        v = self.calculo(a)
        if v is None:
            return None
        if self.agregacion in ("suma", "promedio_mensual") and a.meses > 1:
            return v / a.meses
        return v


def _div(n, d, factor=1.0):
    if n is None or not d:
        return None
    return n / d * factor


FUENTE_BASE = "Casos válidos (sin anulados) y trabajadores activos facturados por cliente y mes"

CATALOGO: list[KPI] = [
    # ---------------------------------------------------------------- Nivel 1: ejecutivos
    KPI("tasa", "Tasa de incidencia", 1, "casos por 100 trabajadores", "decimal2", "baja", "razon",
        "casos ÷ trabajadores activos × 100", FUENTE_BASE,
        "Riesgo real de accidentarse: permite comparar meses, sectores y clientes de distinto tamaño.",
        "Mide frecuencia, no gravedad. No hay meta oficial: se compara contra el propio historial.",
        None, lambda a: _div(a.casos, a.trab, 100)),
    KPI("casos", "Casos", 1, "casos", "entero", "baja", "suma",
        "número de casos válidos", "Casos (se excluyen los anulados)",
        "Volumen de incidentes a gestionar.",
        "Crece también cuando crece la planta de trabajadores: leerlo junto a la tasa.",
        None, lambda a: a.casos),
    KPI("costo", "Costo de los casos", 1, "pesos", "cop", "baja", "suma",
        "suma del costo de los casos válidos", "Casos: campo costo",
        "Impacto económico de la siniestralidad.",
        "Sensible a pocos casos de costo extremo (ver calidad de datos).",
        None, lambda a: a.costo),
    KPI("severidad", "Días perdidos por cada 100 trabajadores", 1, "días por 100 trabajadores", "decimal1", "baja", "razon",
        "días de ausencia ÷ trabajadores activos × 100", "Casos: campo dias_ausencia",
        "Gravedad acumulada: cuántos días de trabajo se pierden, no solo cuántos casos ocurren.",
        "Los casos abiertos pueden sumar más días al cerrarse: el último mes puede subestimarse.",
        "dias", lambda a: _div(a.dias, a.trab, 100)),
    KPI("criticos", "Clientes en estado crítico", 1, "clientes", "conteo", "baja", "promedio_mensual",
        "clientes con tasa del mes > umbral crítico", "Regla oficial de la prueba (pregunta 2.3), umbral configurable",
        "Cuántos clientes están fuera del nivel aceptable definido por la organización.",
        "En clientes muy pequeños un solo caso puede superar el umbral: revisar su tamaño.",
        None, lambda a: a.criticos),
    KPI("cobertura_prevencion", "Cobertura de prevención", 1, "% de clientes con actividad", "pct1", "sube", "razon",
        "clientes con ≥ 1 actividad de prevención en el mes ÷ clientes con facturación", "Prevención + facturación",
        "Qué parte de la cartera recibió acompañamiento preventivo.",
        "Mide alcance, no calidad ni efecto de la actividad. Sin meta oficial.",
        "prevencion", lambda a: _div(a.clientes_con_prev, a.clientes)),
    # ---------------------------------------------------------------- Nivel 2: explicativos
    KPI("trabajadores", "Trabajadores activos (exposición)", 2, "trabajadores", "entero", "neutro", "suma",
        "suma de trabajadores activos facturados", "Facturación",
        "Tamaño de la población expuesta: explica cambios de casos que no son cambios de riesgo.",
        "Proviene de la facturación: si un cliente no factura un mes, su exposición no se cuenta.",
        None, lambda a: a.trab),
    KPI("pct_graves", "Participación de casos graves", 2, "% de los casos", "pct1", "baja", "razon",
        "casos graves ÷ casos", "Casos: campo tipo (oficial)",
        "Composición de la siniestralidad: más graves implica más costo y más días perdidos.",
        "El tipo no siempre concuerda con los días de ausencia (ver calidad de datos).",
        None, lambda a: _div(a.graves, a.casos)),
    KPI("costo_caso", "Costo promedio por caso", 2, "pesos por caso", "cop", "baja", "razon",
        "costo ÷ casos", "Casos",
        "Explica si el costo cambia por más casos (volumen) o por casos más caros (severidad).",
        "Afectado por costos extremos.",
        None, lambda a: _div(a.costo, a.casos)),
    KPI("pct_costo_graves", "Participación de los graves en el costo", 2, "% del costo", "pct1", "neutro", "razon",
        "costo de casos graves ÷ costo total", "Casos",
        "Dónde está el dinero: en general pocos casos graves explican la mayor parte del costo.",
        "Descriptivo.", None, lambda a: _div(a.costo_grave, a.costo)),
    KPI("dias_caso", "Días de ausencia por caso", 2, "días por caso", "decimal1", "baja", "razon",
        "días de ausencia ÷ casos", "Casos: campo dias_ausencia",
        "Duración promedio de la incapacidad.", "Casos abiertos aún pueden sumar días.",
        "dias", lambda a: _div(a.dias, a.casos)),
    KPI("prevencion_100", "Actividades de prevención por 100 trabajadores", 2, "actividades por 100 trabajadores", "decimal2", "neutro", "razon",
        "actividades ÷ trabajadores × 100", "Prevención",
        "Intensidad del esfuerzo preventivo relativa al tamaño de la cartera.",
        "No mide calidad ni participación efectiva.", "prevencion", lambda a: _div(a.prev, a.trab, 100)),
    KPI("pct_trab_criticos", "Trabajadores en clientes críticos", 2, "% de los trabajadores", "pct1", "baja", "razon",
        "trabajadores de clientes críticos ÷ trabajadores", "Regla oficial de clasificación",
        "Cuánta población está expuesta a clientes en estado crítico (pondera por tamaño).",
        "Depende del umbral configurado.", None, lambda a: _div(a.trab_criticos, a.trab)),
    KPI("costo_facturacion", "Costo de casos por cada $100 facturados", 2, "pesos por cada $100", "decimal1", "neutro", "razon",
        "costo de los casos ÷ valor de contrato × 100", "Casos + facturación (valor_contrato)",
        "Relación entre el costo de la siniestralidad y lo facturado al cliente.",
        "DESCRIPTIVO: en los datos el costo supera al valor facturado (más de 100 por cada 100), lo que sugiere que no "
        "están en la misma base. Validar con Finanzas antes de usarlo como indicador de rentabilidad.",
        "valor", lambda a: _div(a.costo, a.valor, 100)),
    KPI("graves_abiertos", "Casos graves abiertos", 2, "casos", "entero", "neutro", "suma",
        "casos graves del periodo que siguen abiertos a la fecha de corte", "Casos: campo estado",
        "Pendientes de seguimiento con mayor impacto.",
        "Es una foto a la fecha de corte: los meses recientes siempre tienen más casos abiertos.",
        "abiertos", lambda a: a.graves_abiertos, comparable=False),
]

POR_CLAVE = {k.clave: k for k in CATALOGO}


def por_clave(clave: str) -> KPI:
    return POR_CLAVE[clave]


def disponibles(cubo, nivel: int | None = None) -> list[KPI]:
    return [k for k in CATALOGO if (nivel is None or k.nivel == nivel) and (k.requiere is None or cubo.tiene(k.requiere))]


def no_disponibles(cubo) -> list[KPI]:
    return [k for k in CATALOGO if k.requiere and not cubo.tiene(k.requiere)]
