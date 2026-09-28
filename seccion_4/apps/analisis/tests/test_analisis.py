"""
Pruebas de la capa analítica con datos construidos a mano (resultado conocido de antemano).

Escenario: 3 clientes en 2 sectores, 26 meses. Todos con una tasa estable de 2 casos por 100 trabajadores,
salvo un pico sembrado en el cliente "Pico" en el último mes (12 casos donde se esperan ~2).
"""
import csv
import math
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.analisis.servicios import cambio
from apps.analisis.servicios import estadistica as E
from apps.analisis.servicios import motor
from apps.analisis.servicios.comparaciones import comparar
from apps.analisis.servicios.datos import desplazar, obtener_cubo, ventana
from apps.analisis.servicios.explicacion import descomponer
from apps.analisis.servicios.kpis import POR_CLAVE
from apps.core.tests import crear_usuario
from apps.tablero.models import CargaDatos, Cliente, ConfiguracionTablero, Coordinador, IndicadorMensual, Sector
from apps.tablero.servicios.carga_proyecto import cargar
from apps.tablero.servicios.indicadores import Filtros

ULTIMO = date(2026, 8, 1)


def sembrar():
    s1, s2 = Sector.objects.create(nombre="Construcción"), Sector.objects.create(nombre="Salud")
    c1 = Coordinador.objects.create(nombre="Coord A", regional="Norte")
    c2 = Coordinador.objects.create(nombre="Coord B", regional="Sur")
    pico = Cliente.objects.create(nombre="Pico", sector=s1, clase_riesgo=4, coordinador=c1)
    estable = Cliente.objects.create(nombre="Estable", sector=s1, clase_riesgo=4, coordinador=c1)
    otro = Cliente.objects.create(nombre="Otro", sector=s2, clase_riesgo=2, coordinador=c2)
    filas = []
    for p in ventana(ULTIMO, 26):
        for cli in (pico, estable, otro):
            casos = 12 if (cli is pico and p == ULTIMO) else 2
            graves = 1 if casos >= 2 else 0
            filas.append(IndicadorMensual(
                cliente=cli, periodo=p, trabajadores_activos=100, casos=casos, casos_graves=graves,
                costo_leve=Decimal(1_000_000) * (casos - graves), costo_grave=Decimal(10_000_000) * graves,
                dias_ausencia=casos * 5, casos_abiertos=0, casos_graves_abiertos=0, casos_anulados=0,
                actividades_prevencion=0 if cli is pico else 1, participantes_prevencion=0, valor_contrato=Decimal(5_000_000)))
    IndicadorMensual.objects.bulk_create(filas)
    CargaDatos.objects.create(fuente="prueba", descripcion="Escenario de prueba", fecha_corte=date(2026, 8, 31),
                              periodo_desde=filas[0].periodo, periodo_hasta=ULTIMO,
                              variables=["dias_ausencia", "casos_abiertos", "actividades_prevencion", "valor_contrato", "detalle_casos"],
                              calidad={"hallazgos": []})
    return pico, estable, otro, c1


class EstadisticaTests(TestCase):
    def test_poisson_valores_conocidos(self):
        # P(X >= 5 | lambda = 1) = 1 - sum_{k<5} e^-1 / k! = 0,00366
        self.assertAlmostEqual(E.poisson_cola_superior(5, 1.0), 1 - sum(math.exp(-1) / math.factorial(k) for k in range(5)), places=10)
        self.assertAlmostEqual(E.poisson_cola_inferior(0, 2.0), math.exp(-2), places=10)
        self.assertAlmostEqual(E.poisson_cola_superior(0, 3.0), 1.0)
        # lambda grande (nivel cartera, ~300 casos) no desborda
        self.assertTrue(0.4 < E.poisson_cola_superior(300, 300.0) < 0.6)

    def test_tendencia_solo_si_es_clara(self):
        self.assertEqual(E.tendencia_lineal([1, 2, 3, 4, 5, 6, 7, 8])["direccion"], "sube")
        self.assertEqual(E.tendencia_lineal([5, 4.9, 5.1, 5, 4.95, 5.05, 5, 5.02])["direccion"], "estable")
        self.assertIsNone(E.tendencia_lineal([1, 2, 3]))


class AnalisisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pico, cls.estable, cls.otro, cls.coord = sembrar()
        cls.analista = crear_usuario("analista", "Usuario")
        cls.coordinador = crear_usuario("coord", "Coordinador", coordinador="Coord A")
        cls.consulta_sin_analisis = crear_usuario("tablero_solo")
        g = Group.objects.create(name="Solo tablero")
        from django.contrib.auth.models import Permission
        g.permissions.add(Permission.objects.get(codename="ver_tablero"), Permission.objects.get(codename="ver_todos_los_clientes"))
        cls.consulta_sin_analisis.groups.add(g)

    def setUp(self):
        cache.clear()

    def analisis(self, usuario=None, **kw):
        return motor.analizar(usuario or self.analista, Filtros(mes=ULTIMO, **kw))

    def test_kpis_formula_exacta(self):
        a = self.analisis()
        self.assertEqual(a["kpis"]["casos"]["valor"], 16)
        self.assertAlmostEqual(a["kpis"]["tasa"]["valor"], 16 / 300 * 100)
        self.assertAlmostEqual(a["kpis"]["severidad"]["valor"], 16 * 5 / 300 * 100)
        self.assertAlmostEqual(a["kpis"]["cobertura_prevencion"]["valor"], 2 / 3)
        self.assertEqual(a["kpis"]["criticos"]["valor"], 1)                       # solo "Pico" (12 %) supera 5
        self.assertAlmostEqual(a["kpis"]["tasa"]["referencias"]["promedio_12m"]["valor"], 2.0)
        self.assertAlmostEqual(a["kpis"]["tasa"]["referencias"]["mes_anterior"]["variacion"], (16 / 3 - 2) / 2)

    def test_razon_se_calcula_sobre_la_ventana_no_como_promedio_de_tasas(self):
        cubo = obtener_cubo(self.analista, Filtros(mes=ULTIMO))
        ytd = comparar(cubo, POR_CLAVE["tasa"], ULTIMO)["ytd"]
        casos = 2 * 3 * 7 + 16
        self.assertAlmostEqual(ytd["valor"], casos / (300 * 8) * 100)

    def test_descomposicion_suma_exactamente_la_variacion(self):
        cubo = obtener_cubo(self.analista, Filtros(mes=ULTIMO))
        d = descomponer(cubo, [ULTIMO], [desplazar(ULTIMO, -1)])
        self.assertAlmostEqual(d["casos"]["exposicion"] + d["casos"]["riesgo"], d["casos"]["total"])
        self.assertAlmostEqual(d["tasa"]["mezcla"] + d["tasa"]["intra"], d["tasa"]["total"])
        self.assertAlmostEqual(d["costo"]["volumen"] + d["costo"]["costo_por_caso"], d["costo"]["total"], places=2)
        self.assertAlmostEqual(d["casos"]["exposicion"], 0)                      # mismos trabajadores: todo es riesgo

    def test_detecta_el_pico_sembrado_y_no_inventa_otros(self):
        a = self.analisis()
        nombres = [x["nombre"] for x in a["anomalias"]["clientes"]]
        self.assertEqual(nombres, ["Pico"])
        self.assertEqual(a["serie"][-1]["anomalia"], "pico")
        self.assertTrue(all(s["anomalia"] is None for s in a["serie"][:-1]))    # meses estables: sin falsas alarmas
        self.assertTrue(any("Pico" in al.titulo for al in a["alertas"]))
        self.assertEqual(a["kpis"]["tasa"]["juicio"]["estado"], "peor")

    def test_prioriza_brecha_de_prevencion(self):
        a = self.analisis()
        self.assertEqual([s["nombre"] for s in a["sin_prevencion"]], ["Pico"])

    def test_resumen_corto_solo_hechos(self):
        r = self.analisis()["resumen"]
        self.assertLessEqual(len(r["puntos"]), 4)                                # resumen ejecutivo corto
        self.assertTrue(all(p["tipo"] == "hecho" for p in r["puntos"]))          # las hipótesis no van en el resumen
        self.assertIn("16 casos", r["puntos"][0]["texto"])
        self.assertIn("por encima de su nivel habitual", r["puntos"][0]["texto"])
        self.assertEqual(r["puntos"][0]["tono"], "alerta")
        self.assertEqual(r["advertencia"]["tipo"], "advertencia")

    def test_no_presenta_cumplimiento_sin_meta(self):
        r = self.analisis()["resumen"]
        texto = " ".join(p["texto"] for p in r["puntos"]).lower()
        self.assertNotIn("cumplimiento", texto)
        self.assertIn("no existen metas", r["advertencia"]["texto"].lower())

    def test_cambio_con_periodo_y_criterio_elegibles(self):
        cubo = obtener_cubo(self.analista, Filtros(mes=ULTIMO))
        for periodo in cambio.PERIODOS:
            for comp in cambio.COMPARACIONES:
                c = cambio.analizar(cubo, ULTIMO, cambio.normalizar(periodo, comp, "cliente", "casos"))
                self.assertTrue(c["disponible"], (periodo, comp))
                d = c["d"]["casos"]
                self.assertAlmostEqual(d["exposicion"] + d["riesgo"], d["total"])          # exacta en cualquier ventana
                self.assertEqual(sum(x["delta"] for x in c["filas"]), d["total"])          # la contribución suma el total
        # trimestre: jun–ago 2026 vs mar–may 2026 → solo el pico (+10) cambia
        c = cambio.analizar(cubo, ULTIMO, cambio.normalizar("trimestre", "anterior", "cliente", "casos"))
        self.assertEqual((c["actual"], c["base"]), ("jun–ago 2026", "mar–may 2026"))
        self.assertEqual([(x["nombre"], x["delta"]) for x in c["filas"]], [("Pico", 10)])
        self.assertLess(c["p"], 0.05)                                                  # 28 vs 18 esperables: p ≈ 2 %
        self.assertTrue(cambio.analizar(cubo, ULTIMO, cambio.normalizar("mes", "anterior", "sector", "casos"))["significativo"])
        # año corrido siempre contra el mismo tramo del año anterior
        actual, base = cambio.ventanas(ULTIMO, "ytd", "anio")
        self.assertEqual((len(actual), base[0]), (8, date(2025, 1, 1)))
        # valores desconocidos vuelven a los valores por defecto; sin datos base se informa, no se inventa
        self.assertEqual(cambio.normalizar("x", "y", "z", "w"),
                         {"periodo": "mes", "comp": "anterior", "por": "sector", "medida": "casos"})
        viejo = cambio.analizar(cubo, desplazar(ULTIMO, -20), cambio.normalizar("12m", None, None, None))
        self.assertFalse(viejo["disponible"])
        self.assertIn("No hay datos", viejo["motivo"])

    def test_alcance_del_coordinador(self):
        a = self.analisis(self.coordinador)
        self.assertEqual({c.nombre for c in a["cubo"].clientes.values()}, {"Pico", "Estable"})
        self.assertEqual(a["kpis"]["casos"]["valor"], 14)

    def test_cache_se_invalida_al_cambiar_umbral(self):
        antes = self.analisis()["kpis"]["criticos"]["valor"]
        cfg = ConfiguracionTablero.actual()
        cfg.umbral_critico = 20
        cfg.save()
        self.assertEqual(antes, 1)
        self.assertEqual(self.analisis()["kpis"]["criticos"]["valor"], 0)

    def test_vistas_y_permisos(self):
        self.client.force_login(self.analista)
        for url in ["analisis:resumen", "analisis:diagnostico", "analisis:calidad", "analisis:metodologia"]:
            self.assertEqual(self.client.get(reverse(url)).status_code, 200, url)
        r = self.client.get(reverse("analisis:diagnostico"), {"dim": "sector", "valor": self.pico.sector_id, "cliente": self.pico.id})
        self.assertContains(r, "Evolución mensual")
        r = self.client.get(reverse("analisis:resumen"), {"periodo": "trimestre", "por": "clase", "medida": "costo"})
        self.assertContains(r, "mar–may 2026")
        self.assertContains(r, 'value="trimestre"', count=2)                      # el filtro global conserva la elección
        self.client.force_login(self.consulta_sin_analisis)
        self.assertEqual(self.client.get(reverse("analisis:resumen")).status_code, 403)
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("analisis:calidad")).status_code, 403)     # sin ver_calidad_datos
        r = self.client.get(reverse("analisis:diagnostico"), {"dim": "sector", "valor": self.otro.sector_id, "cliente": self.otro.id})
        self.assertEqual(r.status_code, 404)                                               # cliente fuera de su cartera

    def test_parametros_invalidos(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.get(reverse("analisis:diagnostico"), {"dim": "sql;drop"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("analisis:resumen"), {"mes": "2031-01"}).status_code, 404)


class CargaProyectoTests(TestCase):
    """El cargador detecta y trata los problemas de calidad sembrados."""

    def _escribir(self, carpeta: Path, nombre, filas):
        with (carpeta / f"{nombre}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0]))
            w.writeheader()
            w.writerows(filas)

    def test_hallazgos_y_tratamientos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "fecha_corte.txt").write_text("2026-09-24", encoding="utf-8")
            self._escribir(d, "clientes", [{"id_cliente": "1", "nombre": "A", "sector": "Salud", "clase_riesgo": "3", "estado": "activo", "fecha_vinculacion": "2020-01-01"}])
            self._escribir(d, "coordinadores", [{"id_coordinador": "1", "nombre_coordinador": "C1", "correo": "c1@x.co", "regional": "Norte"}])
            self._escribir(d, "asignacion_coordinador", [{"id_cliente": "1", "id_coordinador": "1", "correo": "c1@x.co", "vigente_desde": "2026-01-01"}])
            self._escribir(d, "facturacion", [
                {"id_cliente": "1", "periodo": "2026-08-01", "trabajadores_activos": "100", "valor_contrato": "5000000"},
                {"id_cliente": "1", "periodo": "2026-09-01", "trabajadores_activos": "100", "valor_contrato": "5000000"}])
            base = {"id_cliente": "1", "id_trabajador": "1", "costo": "1000000"}
            self._escribir(d, "casos", [
                {**base, "id_caso": "1", "fecha_ocurrencia": "2026-08-03", "tipo": "leve", "dias_ausencia": "2", "estado": "cerrado"},
                {**base, "id_caso": "2", "fecha_ocurrencia": "2026-08-04", "tipo": "grave", "dias_ausencia": "3", "estado": "abierto"},  # tipo vs días
                {**base, "id_caso": "3", "fecha_ocurrencia": "2026-08-05", "tipo": "leve", "dias_ausencia": "1", "estado": "anulado"},
                {**base, "id_caso": "3", "fecha_ocurrencia": "2026-08-05", "tipo": "leve", "dias_ausencia": "1", "estado": "cerrado"},   # duplicado
                {**base, "id_caso": "4", "fecha_ocurrencia": "2026-12-01", "tipo": "leve", "dias_ausencia": "1", "estado": "cerrado"},   # futuro
                {**base, "id_caso": "5", "fecha_ocurrencia": "2026-09-10", "tipo": "leve", "dias_ausencia": "1", "estado": "cerrado"},   # mes en curso
            ])
            self._escribir(d, "prevencion", [{"id_actividad": "1", "id_cliente": "1", "fecha": "2026-08-10", "tipo": "Capacitación", "participantes": "20"}])
            carga = cargar(d)
        codigos = {h["codigo"]: h["registros"] for h in carga.calidad["hallazgos"]}
        for cod in ("CASO_DUPLICADO", "CASO_ANULADO", "CASO_FECHA_INVALIDA", "TIPO_VS_DIAS", "CASO_MES_EN_CURSO", "MES_EN_CURSO", "SIN_METAS"):
            self.assertIn(cod, codigos, cod)
        ago = IndicadorMensual.objects.get()
        self.assertEqual(ago.periodo, date(2026, 8, 1))                 # septiembre (incompleto) excluido
        self.assertEqual(ago.casos, 2)                                   # sin anulado, duplicado, futuro ni mes en curso
        self.assertEqual(ago.casos_graves, 1)                            # se respeta el campo oficial 'tipo'
        self.assertEqual(ago.casos_anulados, 1)
        self.assertEqual(ago.actividades_prevencion, 1)
        self.assertEqual(carga.periodo_hasta, date(2026, 8, 1))
