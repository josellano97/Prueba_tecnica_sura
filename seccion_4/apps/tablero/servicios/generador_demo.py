"""
Generador de datos de demostración.

Es una traducción fiel del generador del tablero HTML original (primera versión de esta sección): mismo PRNG (mulberry32
con aritmética de 32 bits como en JavaScript), mismo orden de llamadas aleatorias y mismas reglas
de redondeo (Math.round). Así la aplicación Django muestra los mismos datos que el tablero original,
lo que permite verificar que la migración no cambió ningún número.

En producción este módulo se reemplaza por una carga desde el Lakehouse (ver README).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

SEMILLA = 20260925
N_CLIENTES = 80
N_MESES = 24
SECTORES = {
    "Manufactura": [3, 4, 5], "Construcción": [4, 5], "Comercio": [1, 2], "Salud": [2, 3],
    "Transporte y logística": [3, 4], "Servicios profesionales": [1, 2], "Agroindustria": [3, 4],
    "Minería y energía": [4, 5],
}
TASA_BASE_CLASE = {1: 0.35, 2: 0.8, 3: 1.5, 4: 2.5, 5: 3.6}          # casos por 100 trabajadores / mes
PROB_GRAVE_CLASE = {1: 0.08, 2: 0.12, 3: 0.18, 4: 0.24, 5: 0.30}
COORDINADORES = ["Ana Restrepo", "Carlos Mejía", "Diana Rojas", "Felipe Duque", "Laura Gómez", "Mateo Ortiz"]
NOMBRES = ["Andina", "Pacífico", "Cordillera", "Horizonte", "Nogal", "Sabana", "Caribe", "Altamira", "Guadua",
           "Ceiba", "Magdalena", "Orinoco", "Tequendama", "Quimbaya", "Arrayán", "Samán", "Palmira", "Zenú",
           "Tayrona", "Farallones"]
SUFIJOS = ["S.A.S.", "S.A.", "Ltda.", "Group"]
ESTACIONAL = [0.9, 0.95, 1.05, 1.0, 1.05, 1.0, 1.1, 1.1, 1.05, 1.0, 0.95, 0.8]
M32 = 0xFFFFFFFF


def crear_aleatorio(semilla: int):
    """mulberry32, idéntico a la versión JavaScript (enteros de 32 bits sin signo)."""
    a = semilla & M32

    def rnd() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & M32
        t = ((a ^ (a >> 15)) * (1 | a)) & M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & M32)) & M32) ^ t
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return rnd


def redondear_js(x: float) -> int:
    """Math.round de JavaScript (0,5 redondea hacia arriba)."""
    return math.floor(x + 0.5)


def normal(rnd) -> float:
    return math.sqrt(-2 * math.log(1 - rnd())) * math.cos(2 * math.pi * rnd())


def poisson(rnd, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 40:
        return max(0, redondear_js(lam + math.sqrt(lam) * normal(rnd)))
    limite, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rnd()
        if not p > limite:
            break
    return k - 1


def elegir(rnd, lista):
    return lista[math.floor(rnd() * len(lista))]


@dataclass
class ClienteDemo:
    id: int
    nombre: str
    sector: str
    clase: int
    coordinador: str
    tamano: int
    efecto: float
    crecimiento: float


@dataclass
class DatosDemo:
    meses: list[date]
    clientes: list[ClienteDemo]
    hechos: list[dict] = field(default_factory=list)


def generar(hoy: date | None = None) -> DatosDemo:
    """Genera 80 clientes y 24 meses cerrados que terminan en el mes anterior a `hoy`."""
    rnd = crear_aleatorio(SEMILLA)
    hoy = hoy or date.today()
    ultimo = (hoy.year * 12 + hoy.month - 1) - 1          # índice absoluto del último mes cerrado
    meses = [date((ultimo - i) // 12, (ultimo - i) % 12 + 1, 1) for i in range(N_MESES - 1, -1, -1)]

    sectores = list(SECTORES)
    usados: set[str] = set()
    clientes: list[ClienteDemo] = []
    for i in range(1, N_CLIENTES + 1):
        sector = elegir(rnd, sectores)
        while True:
            nombre = f"{elegir(rnd, NOMBRES)} {sector.split(' ')[0]} {elegir(rnd, SUFIJOS)}"
            if nombre not in usados:
                break
        usados.add(nombre)
        clase = elegir(rnd, SECTORES[sector])
        coordinador = COORDINADORES[(i * 7) % len(COORDINADORES)]
        tamano = redondear_js(min(2500, max(15, math.exp(4.6 + 0.9 * normal(rnd)))))
        efecto = math.exp(0.45 * normal(rnd))
        crecimiento = 0.004 + 0.01 * normal(rnd)
        clientes.append(ClienteDemo(i, nombre, sector, clase, coordinador, tamano, efecto, crecimiento))

    datos = DatosDemo(meses=meses, clientes=clientes)
    for c in clientes:
        for k, m in enumerate(meses):
            trabajadores = max(5, redondear_js(c.tamano * math.pow(1 + c.crecimiento, k) * (1 + 0.03 * normal(rnd))))
            tasa = TASA_BASE_CLASE[c.clase] * c.efecto * ESTACIONAL[m.month - 1] * (1 - 0.004 * k)
            casos = poisson(rnd, tasa * trabajadores / 100)
            graves, costo_leve, costo_grave = 0, 0.0, 0.0
            for _ in range(casos):
                if rnd() < PROB_GRAVE_CLASE[c.clase]:
                    graves += 1
                    dias = 16 + 44 * -math.log(1 - rnd())
                    costo_grave += dias * (260000 + 160000 * rnd()) + 1.5e6 + 7.5e6 * rnd()
                else:
                    dias = math.floor(12 * rnd())
                    costo_leve += dias * (150000 + 110000 * rnd()) + 80000 + 620000 * rnd()
            datos.hechos.append({"cliente": c.id, "periodo": m, "trabajadores": trabajadores, "casos": casos,
                                 "graves": graves, "costo_leve": costo_leve, "costo_grave": costo_grave})
    return datos
