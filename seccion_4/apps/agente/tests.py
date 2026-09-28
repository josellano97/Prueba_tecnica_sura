"""Pruebas de la API del agente: token obligatorio, alcance del usuario y mismas cifras que el tablero."""
from django.test import TestCase
from django.urls import reverse

from apps.analisis.tests.test_analisis import ULTIMO, sembrar
from apps.core.tests import crear_usuario
from apps.tablero.servicios.indicadores import Filtros, calcular_tablero

from .models import TokenAgente


class ApiAgenteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pico, cls.estable, cls.otro, _ = sembrar()
        cls.consulta = crear_usuario("consulta", "Consulta")
        cls.coordinador = crear_usuario("coord", "Coordinador", coordinador="Coord A")
        _, cls.token = TokenAgente.crear("prueba", cls.consulta)
        _, cls.token_coord = TokenAgente.crear("prueba coordinador", cls.coordinador)

    def get(self, vista, token=None, **params):
        kwargs = {"cliente_id": params.pop("cliente_id")} if "cliente_id" in params else {}
        cab = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(reverse(f"agente:{vista}", kwargs=kwargs), params, **cab)

    def test_sin_token_o_con_token_invalido_responde_401(self):
        self.assertEqual(self.get("resumen").status_code, 401)
        self.assertEqual(self.get("resumen", "agt_falso").status_code, 401)
        TokenAgente.objects.filter(usuario=self.consulta).update(activo=False)
        self.assertEqual(self.get("resumen", self.token).status_code, 401)

    def test_resumen_da_las_mismas_cifras_que_el_tablero(self):
        r = self.get("resumen", self.token).json()
        esperado = calcular_tablero(self.consulta, Filtros(mes=ULTIMO))["kpis"]["actual"]
        self.assertEqual(r["casos"], esperado["casos"])
        self.assertAlmostEqual(r["tasa"], esperado["tasa"])
        self.assertEqual(r["mes_analizado"], ULTIMO.isoformat()[:7])
        self.assertIn("fecha_corte", r)
        self.assertIn("/tablero/?mes=", r["enlace_tablero"])

    def test_buscar_cliente_sin_importar_tildes_ni_mayusculas(self):
        r = self.get("buscar_clientes", self.token, nombre="PICO").json()
        self.assertEqual([c["cliente"] for c in r["clientes"]], ["Pico"])
        self.assertEqual(self.get("buscar_clientes", self.token, nombre="x").status_code, 400)

    def test_cliente_con_nivel_de_riesgo(self):
        r = self.get("cliente", self.token, cliente_id=self.pico.id).json()
        self.assertEqual(r["mes"]["casos"], 12)
        self.assertEqual(r["mes"]["nivel_de_riesgo"], "crítico")          # 12 casos / 100 trabajadores
        self.assertEqual(r["mes_anterior"]["casos"], 2)

    def test_coordinador_solo_ve_su_cartera(self):
        self.assertEqual(self.get("cliente", self.token_coord, cliente_id=self.otro.id).status_code, 404)
        r = self.get("buscar_clientes", self.token_coord, nombre="otro").json()
        self.assertEqual(r["total"], 0)
        self.assertEqual(self.get("resumen", self.token_coord).json()["casos"], 14)   # Pico 12 + Estable 2

    def test_criticos_top_glosario_y_mes_invalido(self):
        self.assertEqual([c["cliente"] for c in self.get("criticos", self.token).json()["clientes_criticos"]], ["Pico"])
        self.assertEqual(self.get("top", self.token, n=1).json()["top_clientes_por_casos"][0]["cliente"], "Pico")
        self.assertIn("critico", self.get("glosario", self.token).json()["niveles_de_riesgo"])
        r = self.get("resumen", self.token, mes="2031-01")
        self.assertEqual(r.status_code, 404)
        self.assertIn("No hay datos", r.json()["error"])

    def test_solo_lectura(self):
        r = self.client.post(reverse("agente:resumen"), HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(r.status_code, 405)


CHAT = {"AGENTE_CHAT_URL": "https://ejemplo.app.n8n.cloud/webhook/abc/chat",
        "AGENTE_CHAT_USUARIO": "sura", "AGENTE_CHAT_CLAVE": "clave-de-prueba"}


class AsistenteEmbebidoTests(TestCase):
    """La burbuja del asistente solo aparece configurada y para roles que ven toda la cartera."""

    @classmethod
    def setUpTestData(cls):
        sembrar()
        cls.analista = crear_usuario("analista", "Usuario")
        cls.coordinador = crear_usuario("coord", "Coordinador", coordinador="Coord A")

    def pagina(self, usuario):
        self.client.force_login(usuario)
        return self.client.get(reverse("analisis:resumen"))

    def test_sin_configuracion_no_aparece(self):
        self.assertNotContains(self.pagina(self.analista), 'id="asistente"')

    def test_aparece_para_quien_ve_toda_la_cartera_y_la_csp_permite_solo_ese_dominio(self):
        from django.test import override_settings
        from apps.core.middleware import CabecerasSeguridadMiddleware
        with override_settings(**CHAT):
            r = self.pagina(self.analista)
            self.assertContains(r, 'id="asistente"')
            self.assertContains(r, "js/asistente")
            csp = CabecerasSeguridadMiddleware(lambda req: None).csp
            self.assertIn("connect-src 'self' https://ejemplo.app.n8n.cloud", csp)

    def test_no_aparece_para_un_coordinador(self):
        from django.test import override_settings
        with override_settings(**CHAT):
            self.assertNotContains(self.pagina(self.coordinador), 'id="asistente"')    # el agente ve toda la cartera

    def test_pestana_agente_sura(self):
        from django.test import override_settings
        with override_settings(**CHAT):
            html = self.pagina(self.analista).content.decode()
            self.assertIn('href="/agente/"', html)                                      # en el menú lateral
            self.assertIn("Agente Sura", html)
            r = self.client.get(reverse("agente_chat"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'id="asistente-mensajes"')
            self.assertNotContains(r, 'id="asistente-abrir"')                            # sin la burbuja flotante
            self.client.force_login(self.coordinador)
            self.assertEqual(self.client.get(reverse("agente_chat")).status_code, 403)
            self.assertNotContains(self.client.get(reverse("analisis:resumen")), 'href="/agente/"')
        self.client.force_login(self.analista)
        self.assertEqual(self.client.get(reverse("agente_chat")).status_code, 403)       # sin configurar
