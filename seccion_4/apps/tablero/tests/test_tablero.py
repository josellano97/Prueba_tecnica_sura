from datetime import date

from django.db.models import Sum
from django.urls import reverse

from apps.core.tests import ConDatos
from apps.tablero.models import Cliente, ConfiguracionTablero, IndicadorMensual
from apps.tablero.servicios import generador_demo


class GeneradorTests(ConDatos):
    def test_mismos_datos_que_el_tablero_html_original(self):
        # Valores que mostraba el tablero HTML original para agosto de 2026 (mismo generador)
        ago = IndicadorMensual.objects.filter(periodo=date(2026, 8, 1)).aggregate(
            casos=Sum("casos"), trab=Sum("trabajadores_activos"))
        self.assertEqual(ago["casos"], 279)
        self.assertEqual(ago["trab"], 12627)
        self.assertEqual(Cliente.objects.count(), 80)
        self.assertEqual(IndicadorMensual.objects.count(), 80 * 24)

    def test_generador_es_reproducible(self):
        a, b = generador_demo.generar(date(2026, 9, 25)), generador_demo.generar(date(2026, 9, 25))
        self.assertEqual(a.hechos, b.hechos)


class ApiDatosTests(ConDatos):
    def datos(self, usuario, **params):
        self.client.force_login(usuario)
        r = self.client.get(reverse("tablero:datos"), params)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_kpis_del_mes_por_defecto(self):
        d = self.datos(self.analista)
        self.assertEqual(d["mes"]["valor"], "2026-08-01")
        a, p = d["kpis"]["actual"], d["kpis"]["anterior"]
        self.assertEqual(a["casos"], 279)
        self.assertAlmostEqual(a["tasa"], 279 / 12627 * 100)
        self.assertEqual(a["casos"] - p["casos"], 27)                 # "27 más que en julio" en el original
        self.assertAlmostEqual(a["costo"] / 1e9, 1.98, places=2)
        self.assertEqual(a["criticos"], 10)
        self.assertEqual(sum(c["casos"] for c in d["por_clase"]), a["casos"])
        self.assertEqual(len(d["tendencia"]), 12)
        self.assertEqual(len(d["top"]["mes"]), 10)

    def test_filtros_por_sector_clase_y_mes(self):
        base = self.datos(self.analista)
        cliente = Cliente.objects.filter(clase_riesgo__in=[4, 5]).select_related("sector").first()
        d = self.datos(self.analista, mes="2026-03", sector=cliente.sector_id, clase=[4, 5])
        esperado = IndicadorMensual.objects.filter(periodo=date(2026, 3, 1), cliente__sector=cliente.sector_id,
                                                   cliente__clase_riesgo__in=[4, 5]).aggregate(s=Sum("casos"))["s"]
        self.assertEqual(d["kpis"]["actual"]["casos"], esperado)
        self.assertLess(d["alcance"]["filtrados"], base["alcance"]["filtrados"])
        self.assertTrue(all(f["clase"] in (4, 5) for f in d["top"]["mes"]))
        self.assertEqual(d["tendencia"][-1]["periodo"], "2026-03-01")

    def test_filtros_invalidos_devuelven_400(self):
        self.client.force_login(self.analista)
        for params in ({"mes": "2030-01"}, {"clase": 9}, {"sector": "abc"}, {"mes": "' OR 1=1 --"}):
            self.assertEqual(self.client.get(reverse("tablero:datos"), params).status_code, 400, params)

    def test_coordinador_solo_ve_sus_clientes(self):
        d = self.datos(self.coordinador)
        suyos = Cliente.objects.filter(coordinador__nombre="Ana Restrepo")
        self.assertEqual(d["alcance"]["visibles"], suyos.count())
        self.assertTrue(d["alcance"]["restringido"])
        self.assertTrue(all(f["coordinador"] == "Ana Restrepo" for f in d["top"]["12m"]))
        esperado = IndicadorMensual.objects.filter(periodo=date(2026, 8, 1), cliente__in=suyos).aggregate(s=Sum("casos"))["s"]
        self.assertEqual(d["kpis"]["actual"]["casos"], esperado)

    def test_coordinador_no_puede_ver_otro_coordinador_manipulando_la_url(self):
        otro = Cliente.objects.exclude(coordinador__nombre="Ana Restrepo").first().coordinador_id
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("tablero:datos"), {"coordinador": otro}).status_code, 400)

    def test_usuario_con_permiso_pero_sin_alcance_no_ve_datos(self):
        from apps.core.tests import crear_usuario
        u = crear_usuario("sin_cartera", "Coordinador")          # rol sin 'ver todos' y sin coordinador
        self.client.force_login(u)
        self.assertContains(self.client.get(reverse("tablero:inicio")), "No tiene clientes asignados")
        self.assertEqual(self.client.get(reverse("tablero:datos")).json()["alcance"]["visibles"], 0)

    def test_umbral_configurable_cambia_la_clasificacion(self):
        cfg = ConfiguracionTablero.actual()
        cfg.umbral_critico = 50
        cfg.save()
        self.assertEqual(self.datos(self.analista)["kpis"]["actual"]["criticos"], 0)


class ExportacionTests(ConDatos):
    def test_exportar_requiere_permiso(self):
        self.client.force_login(self.consulta)                    # Consulta: sin permiso de exportar
        self.assertEqual(self.client.get(reverse("tablero:exportar_top")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("tablero:inicio")), "Exportar CSV")

    def test_exportar_csv(self):
        self.client.force_login(self.analista)
        r = self.client.get(reverse("tablero:exportar_top"), {"mes": "2026-08", "periodo": "12m"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        lineas = r.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(lineas), 11)                          # encabezado + 10 clientes
        self.assertTrue(lineas[0].startswith("posicion;cliente"))


class ConfiguracionTests(ConDatos):
    def test_administrador_cambia_umbrales_con_validacion(self):
        self.client.force_login(self.admin)
        url = reverse("tablero:configuracion")
        r = self.client.post(url, {"nombre_organizacion": "SURA", "umbral_moderado": "6", "umbral_critico": "5"})
        self.assertContains(r, "El umbral moderado debe ser menor")
        r = self.client.post(url, {"nombre_organizacion": "SURA", "umbral_moderado": "2.5", "umbral_critico": "6"})
        self.assertRedirects(r, url)
        self.assertEqual(float(ConfiguracionTablero.actual().umbral_critico), 6.0)

    def test_usuario_normal_no_ve_ni_cambia_la_configuracion(self):
        self.client.force_login(self.analista)
        self.assertEqual(self.client.post(reverse("tablero:configuracion"), {"umbral_critico": "1"}).status_code, 403)
