from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from apps.core.tests import CLAVE, ConDatos, crear_usuario
from apps.tablero.models import Coordinador

Usuario = get_user_model()


def datos_usuario(**extra):
    base = {"username": "nuevo", "email": "nuevo@ejemplo.co", "first_name": "Nuevo", "last_name": "Usuario",
            "is_active": "on", "contrasena1": "Clave-Nueva-2026!", "contrasena2": "Clave-Nueva-2026!"}
    base.update(extra)
    return base


class AccesoPorRolTests(ConDatos):
    def entrar(self, u):
        self.client.force_login(u)

    def test_administrador_accede_a_todo(self):
        self.entrar(self.admin)
        for url in [reverse("tablero:inicio"), reverse("cuentas:usuarios"), reverse("cuentas:usuario_crear"),
                    reverse("cuentas:roles"), reverse("cuentas:rol_crear"), reverse("tablero:configuracion"),
                    reverse("admin:index")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_usuario_normal_ve_tablero_pero_no_administracion(self):
        self.entrar(self.analista)
        self.assertEqual(self.client.get(reverse("tablero:inicio")).status_code, 200)
        for url in [reverse("cuentas:usuarios"), reverse("cuentas:usuario_crear"), reverse("cuentas:roles"),
                    reverse("tablero:configuracion"), reverse("cuentas:usuario_editar", args=[self.admin.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # tampoco con peticiones directas de escritura
        self.assertEqual(self.client.post(reverse("cuentas:usuario_estado", args=[self.consulta.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("cuentas:usuario_crear"), datos_usuario()).status_code, 403)
        self.assertFalse(Usuario.objects.filter(username="nuevo").exists())
        # el admin de Django lo manda a su propio login (no es staff)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_menu_muestra_solo_lo_permitido(self):
        self.entrar(self.analista)
        html = self.client.get(reverse("tablero:inicio")).content.decode()
        self.assertIn('href="/tablero/"', html)
        self.assertNotIn('href="/cuentas/usuarios/"', html)
        self.entrar(self.admin)
        self.assertIn('href="/cuentas/usuarios/"', self.client.get(reverse("tablero:inicio")).content.decode())

    def test_usuario_sin_rol_no_ve_el_tablero(self):
        self.entrar(self.sin_rol)
        self.assertEqual(self.client.get(reverse("tablero:inicio")).status_code, 403)
        self.assertEqual(self.client.get(reverse("tablero:datos")).status_code, 403)

    def test_quitar_permiso_a_un_rol_se_aplica_de_inmediato(self):
        rol = Group.objects.get(name="Usuario")
        rol.permissions.remove(Permission.objects.get(codename="ver_tablero"))
        self.entrar(Usuario.objects.get(pk=self.analista.pk))
        self.assertEqual(self.client.get(reverse("tablero:inicio")).status_code, 403)


class GestionUsuariosTests(ConDatos):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_crear_usuario_con_rol_y_coordinador(self):
        coord = Coordinador.objects.get(nombre="Diana Rojas")
        r = self.client.post(reverse("cuentas:usuario_crear"),
                             datos_usuario(roles=[Group.objects.get(name="Coordinador").pk], coordinador=coord.pk))
        self.assertRedirects(r, reverse("cuentas:usuarios"))
        u = Usuario.objects.get(username="nuevo")
        self.assertTrue(u.check_password("Clave-Nueva-2026!"))       # contraseña guardada con hash
        self.assertNotEqual(u.password, "Clave-Nueva-2026!")
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Coordinador"])
        self.assertEqual(u.perfil.coordinador, coord)
        self.assertTrue(self.client.login(username="nuevo", password="Clave-Nueva-2026!"))

    def test_crear_usuario_valida_contrasena_y_correo_duplicado(self):
        r = self.client.post(reverse("cuentas:usuario_crear"), datos_usuario(contrasena1="123", contrasena2="123"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Usuario.objects.filter(username="nuevo").exists())
        r = self.client.post(reverse("cuentas:usuario_crear"), datos_usuario(email=self.analista.email))
        self.assertContains(r, "Ya existe un usuario con este correo")

    def test_cambiar_rol_de_un_usuario(self):
        r = self.client.post(reverse("cuentas:usuario_editar", args=[self.consulta.pk]), {
            "username": "consulta", "email": "consulta@ejemplo.co", "is_active": "on",
            "roles": [Group.objects.get(name="Usuario").pk]})
        self.assertRedirects(r, reverse("cuentas:usuarios"))
        u = Usuario.objects.get(pk=self.consulta.pk)
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Usuario"])
        self.assertTrue(u.has_perm("tablero.exportar_datos"))
        self.assertTrue(u.check_password(CLAVE))                   # sin contraseña nueva, no cambia

    def test_desactivar_y_activar_usuario(self):
        url = reverse("cuentas:usuario_estado", args=[self.analista.pk])
        self.client.post(url)
        self.assertFalse(Usuario.objects.get(pk=self.analista.pk).is_active)
        self.assertFalse(self.client.login(username="analista", password=CLAVE))
        self.client.force_login(self.admin)
        self.client.post(url)
        self.assertTrue(Usuario.objects.get(pk=self.analista.pk).is_active)

    def test_cambio_de_estado_solo_por_post(self):
        self.assertEqual(self.client.get(reverse("cuentas:usuario_estado", args=[self.analista.pk])).status_code, 405)

    def test_no_puede_desactivarse_a_si_mismo(self):
        self.client.post(reverse("cuentas:usuario_estado", args=[self.admin.pk]))
        self.assertTrue(Usuario.objects.get(pk=self.admin.pk).is_active)

    def test_redireccion_abierta_bloqueada(self):
        r = self.client.post(reverse("cuentas:usuario_estado", args=[self.consulta.pk]), {"siguiente": "https://evil.co/"})
        self.assertRedirects(r, reverse("cuentas:usuarios"))

    def test_administrador_no_ve_ni_edita_superusuarios(self):
        self.assertNotContains(self.client.get(reverse("cuentas:usuarios")), ">root<")
        self.assertEqual(self.client.get(reverse("cuentas:usuario_editar", args=[self.super.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("cuentas:usuario_estado", args=[self.super.pk])).status_code, 404)

    def test_administrador_no_puede_dar_acceso_al_admin_de_django(self):
        self.client.post(reverse("cuentas:usuario_crear"), datos_usuario(is_staff="on"))
        self.assertFalse(Usuario.objects.get(username="nuevo").is_staff)   # el campo se ignora

    def test_busqueda_y_filtros_de_la_lista(self):
        r = self.client.get(reverse("cuentas:usuarios"), {"q": "coordin"})
        self.assertEqual([u.username for u in r.context["usuarios"]], ["coordinadora"])
        r = self.client.get(reverse("cuentas:usuarios"), {"rol": Group.objects.get(name="Consulta").pk})
        self.assertEqual([u.username for u in r.context["usuarios"]], ["consulta"])


class AntiEscalamientoTests(ConDatos):
    """Un gestor de usuarios no puede otorgar permisos que no tiene."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        gestor = Group.objects.create(name="Gestor limitado")
        gestor.permissions.add(*Permission.objects.filter(codename__in=["view_user", "add_user", "change_user", "view_group", "change_group"]))
        cls.gestor = crear_usuario("gestor", "Gestor limitado")

    def setUp(self):
        self.client.force_login(self.gestor)

    def test_no_puede_asignar_rol_con_permisos_que_no_tiene(self):
        r = self.client.post(reverse("cuentas:usuario_crear"), datos_usuario(roles=[Group.objects.get(name="Administrador").pk]))
        self.assertContains(r, "No puede otorgar permisos que usted no tiene")
        self.assertFalse(Usuario.objects.filter(username="nuevo").exists())

    def test_no_puede_ampliar_su_propio_rol(self):
        rol = Group.objects.get(name="Gestor limitado")
        exportar = Permission.objects.get(codename="exportar_datos")
        actuales = list(rol.permissions.values_list("pk", flat=True))
        r = self.client.post(reverse("cuentas:rol_editar", args=[rol.pk]), {"name": rol.name, "permisos": actuales + [exportar.pk]})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(rol.permissions.filter(pk=exportar.pk).exists())


class GestionRolesTests(ConDatos):
    def setUp(self):
        self.client.force_login(self.admin)

    def test_crear_rol_y_asignarlo(self):
        permiso = Permission.objects.get(codename="ver_tablero")
        r = self.client.post(reverse("cuentas:rol_crear"), {"name": "Auditoría", "permisos": [permiso.pk]})
        self.assertRedirects(r, reverse("cuentas:roles"))
        rol = Group.objects.get(name="Auditoría")
        self.assertEqual(list(rol.permissions.all()), [permiso])
        u = crear_usuario("auditor", "Auditoría")
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("tablero:inicio")).status_code, 200)
        self.assertEqual(self.client.get(reverse("tablero:exportar_top")).status_code, 403)

    def test_matriz_de_roles(self):
        r = self.client.get(reverse("cuentas:roles"))
        self.assertContains(r, "Ver el tablero de monitoreo")
        self.assertEqual(len(r.context["matriz"]), 4)

    def test_roles_iniciales_creados_por_migracion(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)) - {"Gestor limitado"},
                         {"Administrador", "Usuario", "Coordinador", "Consulta"})


class AdminDjangoEscalamientoTests(ConDatos):
    def test_staff_no_superusuario_no_puede_volverse_superusuario_en_el_admin(self):
        self.client.force_login(self.admin)            # staff con permisos de usuarios, no superusuario
        url = reverse("admin:auth_user_change", args=[self.admin.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'name="is_superuser"')
        self.assertEqual(self.client.get(reverse("admin:auth_user_change", args=[self.super.pk])).status_code, 302)
