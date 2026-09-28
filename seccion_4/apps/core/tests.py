"""Utilidades de prueba compartidas + pruebas de seguridad transversal (cabeceras, salud, producción)."""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from apps.tablero.models import Coordinador

Usuario = get_user_model()
CLAVE = "Clave-de-prueba-2026"


def crear_usuario(username, rol=None, coordinador=None, **extra):
    u = Usuario.objects.create_user(username=username, password=CLAVE, email=f"{username}@ejemplo.co", **extra)
    if rol:
        u.groups.add(Group.objects.get(name=rol))
    if coordinador:
        u.perfil.coordinador = Coordinador.objects.get(nombre=coordinador)
        u.perfil.save()
    return u


class ConDatos(TestCase):
    """Base con los datos demo (idénticos al tablero original) y un usuario por rol."""

    @classmethod
    def setUpTestData(cls):
        call_command("cargar_datos_demo", fecha=date(2026, 9, 25), stdout=open(os.devnull, "w"))
        cls.admin = crear_usuario("admin", "Administrador", is_staff=True)
        cls.analista = crear_usuario("analista", "Usuario")
        cls.consulta = crear_usuario("consulta", "Consulta")
        cls.coordinador = crear_usuario("coordinadora", "Coordinador", coordinador="Ana Restrepo")
        cls.sin_rol = crear_usuario("sinrol")
        cls.super = Usuario.objects.create_superuser("root", "root@ejemplo.co", CLAVE)


class SeguridadTransversalTests(TestCase):
    def test_salud_responde_sin_sesion(self):
        r = self.client.get("/salud/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"estado": "ok"})

    def test_cabeceras_de_seguridad(self):
        r = self.client.get("/cuentas/ingresar/")
        self.assertIn("script-src 'self'", r["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_paginas_internas_no_se_guardan_en_cache(self):
        crear_usuario("u1", "Usuario")
        self.client.login(username="u1", password=CLAVE)
        self.assertIn("no-store", self.client.get("/tablero/")["Cache-Control"])

    def test_404_personalizado(self):
        r = self.client.get("/no-existe/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "La página no existe", status_code=404)


class ConfiguracionProduccionTests(TestCase):
    """La configuración de producción se niega a arrancar sin secretos y pasa `check --deploy`."""

    raiz = Path(__file__).resolve().parents[2]

    def _ejecutar(self, extra_env):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        env.update({"DJANGO_SETTINGS_MODULE": "config.settings.prod", **extra_env})
        return subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
                              cwd=self.raiz, env=env, capture_output=True, text=True)

    def test_sin_secret_key_no_arranca(self):
        r = self._ejecutar({"DJANGO_ALLOWED_HOSTS": "miapp.azurewebsites.net"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", r.stderr)

    def test_check_deploy_sin_advertencias(self):
        r = self._ejecutar({"DJANGO_SECRET_KEY": "x" * 20 + "k9$Qm2#vT7!pL4@wZ8^rN1&cF6*hJ3(bY5)dS0",
                            "DJANGO_ALLOWED_HOSTS": "miapp.azurewebsites.net"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
