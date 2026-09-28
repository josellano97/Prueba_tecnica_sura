from django.test import TestCase
from django.urls import reverse

from apps.core.tests import CLAVE, crear_usuario


class AutenticacionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = crear_usuario("ana", "Usuario")

    def test_login_correcto_lleva_al_analisis_gerencial(self):
        r = self.client.post(reverse("cuentas:login"), {"username": "ana", "password": CLAVE}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("analisis:resumen"))
        self.assertTrue(r.context["user"].is_authenticated)

    def test_sin_permiso_de_analisis_la_raiz_lleva_al_tablero(self):
        from django.contrib.auth.models import Group, Permission
        g = Group.objects.create(name="Solo tablero")
        g.permissions.add(Permission.objects.get(codename="ver_tablero"))
        u = crear_usuario("solo_tablero")
        u.groups.add(g)
        self.client.force_login(u)
        self.assertRedirects(self.client.get("/"), reverse("tablero:inicio"))

    def test_login_incorrecto_muestra_error_sin_revelar_cual_dato_fallo(self):
        r = self.client.post(reverse("cuentas:login"), {"username": "ana", "password": "incorrecta"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuario o contraseña incorrectos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_usuario_inactivo_no_puede_ingresar(self):
        crear_usuario("inactivo", "Usuario", is_active=False)
        r = self.client.post(reverse("cuentas:login"), {"username": "inactivo", "password": CLAVE})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_paginas_privadas_redirigen_al_login(self):
        for url in ["/", reverse("tablero:inicio"), reverse("cuentas:usuarios"), reverse("cuentas:roles"),
                    reverse("tablero:configuracion"), reverse("cuentas:cambio_contrasena")]:
            r = self.client.get(url, follow=True)
            self.assertEqual(r.resolver_match.url_name, "login", url)

    def test_api_sin_sesion_no_entrega_datos(self):
        r = self.client.get(reverse("tablero:datos"))
        self.assertIn(r.status_code, (302, 403))
        self.assertNotIn("application/json", r.get("Content-Type", ""))

    def test_login_conserva_destino_seguro(self):
        r = self.client.post(reverse("cuentas:login") + "?next=/cuentas/usuarios/",
                             {"username": "ana", "password": CLAVE, "next": "/cuentas/usuarios/"})
        self.assertRedirects(r, "/cuentas/usuarios/", fetch_redirect_response=False)

    def test_login_ignora_destino_externo(self):
        r = self.client.post(reverse("cuentas:login"), {"username": "ana", "password": CLAVE,
                                                         "next": "https://sitio-malicioso.com/"})
        self.assertRedirects(r, reverse("inicio"), fetch_redirect_response=False)

    def test_logout_por_post_cierra_la_sesion(self):
        self.client.login(username="ana", password=CLAVE)
        r = self.client.post(reverse("cuentas:logout"))
        self.assertRedirects(r, reverse("cuentas:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_por_get_no_esta_permitido(self):
        self.client.login(username="ana", password=CLAVE)
        self.assertEqual(self.client.get(reverse("cuentas:logout")).status_code, 405)

    def test_login_exige_token_csrf(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        r = c.post(reverse("cuentas:login"), {"username": "ana", "password": CLAVE})
        self.assertEqual(r.status_code, 403)

    def test_cambio_de_contrasena_valida_politica(self):
        self.client.login(username="ana", password=CLAVE)
        r = self.client.post(reverse("cuentas:cambio_contrasena"),
                             {"old_password": CLAVE, "new_password1": "12345", "new_password2": "12345"})
        self.assertEqual(r.status_code, 200)            # se rechaza: muy corta y numérica
        r = self.client.post(reverse("cuentas:cambio_contrasena"),
                             {"old_password": CLAVE, "new_password1": "Nueva-Clave-Segura-77", "new_password2": "Nueva-Clave-Segura-77"})
        self.assertRedirects(r, reverse("inicio"), fetch_redirect_response=False)
