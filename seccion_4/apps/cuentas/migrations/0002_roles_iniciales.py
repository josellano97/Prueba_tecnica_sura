"""
Crea los roles iniciales (Groups) con sus permisos. Se ejecuta una sola vez: después los roles son
datos que el administrador gestiona; si los modifica o elimina, esta migración no los vuelve a crear.
"""
from django.contrib.auth.management import create_permissions
from django.db import migrations

ROLES = {
    "Administrador": ["tablero.ver_tablero", "tablero.ver_todos_los_clientes", "tablero.exportar_datos",
                      "auth.view_user", "auth.add_user", "auth.change_user",
                      "auth.view_group", "auth.add_group", "auth.change_group",
                      "tablero.view_configuraciontablero", "tablero.change_configuraciontablero"],
    "Usuario": ["tablero.ver_tablero", "tablero.ver_todos_los_clientes", "tablero.exportar_datos"],
    "Coordinador": ["tablero.ver_tablero", "tablero.exportar_datos"],
    "Consulta": ["tablero.ver_tablero", "tablero.ver_todos_los_clientes"],
}


def crear_roles(apps, schema_editor):
    # Los permisos normalmente se crean al final de migrate; aquí se necesitan ya.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for nombre, permisos in ROLES.items():
        grupo, creado = Group.objects.get_or_create(name=nombre)
        if not creado:
            continue
        for completo in permisos:
            app, codename = completo.split(".")
            grupo.permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))


def eliminar_roles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cuentas", "0001_initial"),
        ("tablero", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(crear_roles, eliminar_roles)]
