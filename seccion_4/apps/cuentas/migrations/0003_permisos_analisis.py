"""
Agrega los permisos de la capa analítica a los roles iniciales que sigan existiendo.
El alcance por coordinador se sigue aplicando: un coordinador analiza solo su cartera.
Si un administrador eliminó o renombró un rol, esta migración no lo recrea.
"""
from django.contrib.auth.management import create_permissions
from django.db import migrations

NUEVOS = {
    "Administrador": ["ver_analisis", "ver_calidad_datos"],
    "Usuario": ["ver_analisis", "ver_calidad_datos"],
    "Coordinador": ["ver_analisis"],
    "Consulta": ["ver_analisis"],
}


def agregar(apps, schema_editor):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for rol, codigos in NUEVOS.items():
        grupo = Group.objects.filter(name=rol).first()
        if grupo:
            grupo.permissions.add(*Permission.objects.filter(content_type__app_label="tablero", codename__in=codigos))


def quitar(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = Permission.objects.filter(content_type__app_label="tablero", codename__in=["ver_analisis", "ver_calidad_datos"])
    for grupo in Group.objects.filter(name__in=NUEVOS):
        grupo.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [("cuentas", "0002_roles_iniciales"), ("tablero", "0002_datos_analiticos")]
    operations = [migrations.RunPython(agregar, quitar)]
