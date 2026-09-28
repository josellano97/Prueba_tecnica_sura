"""
Catálogo de permisos que la aplicación sabe interpretar y roles iniciales.

* Los roles iniciales se crean una sola vez en la migración cuentas/0002 (congelada allí, como exige Django). Después son datos: el administrador
  los edita, crea o elimina desde la aplicación o el admin. El código nunca pregunta por el nombre
  de un rol, solo por permisos.
* PERMISOS_ASIGNABLES limita qué permisos se muestran al editar roles/usuarios en la aplicación,
  para no exponer los cientos de permisos técnicos de Django (el admin los sigue mostrando todos).
"""

PERMISOS_ASIGNABLES = [
    # (sección, "app.codename", descripción para el administrador)
    ("Tablero", "tablero.ver_tablero", "Ver el tablero de monitoreo"),
    ("Tablero", "tablero.ver_todos_los_clientes", "Ver todos los clientes (si no, solo los de su coordinador)"),
    ("Tablero", "tablero.exportar_datos", "Exportar datos del tablero a CSV"),
    ("Análisis", "tablero.ver_analisis", "Ver el análisis gerencial, alertas y diagnóstico"),
    ("Análisis", "tablero.ver_calidad_datos", "Ver el reporte de calidad de datos"),
    ("Usuarios", "auth.view_user", "Ver la lista de usuarios"),
    ("Usuarios", "auth.add_user", "Crear usuarios"),
    ("Usuarios", "auth.change_user", "Editar usuarios, activarlos/desactivarlos y asignar roles"),
    ("Roles", "auth.view_group", "Ver roles y sus permisos"),
    ("Roles", "auth.add_group", "Crear roles"),
    ("Roles", "auth.change_group", "Editar los permisos de los roles"),
    ("Configuración", "tablero.view_configuraciontablero", "Ver la configuración del tablero"),
    ("Configuración", "tablero.change_configuraciontablero", "Cambiar umbrales y parámetros del tablero"),
]

DESCRIPCION_ROLES = {
    "Administrador": "Todo: tablero, análisis, usuarios, roles y configuración.",
    "Usuario": "Tablero y análisis de todos los clientes, con exportación y calidad de datos.",
    "Coordinador": "Tablero y análisis limitados a sus clientes asignados, con exportación.",
    "Consulta": "Solo lectura del tablero y del análisis, sin exportar.",
}


def filtro_permisos(Permission):
    """Q de los permisos asignables (se usa con el modelo Permission de la app o de una migración)."""
    from django.db.models import Q

    q = Q(pk__in=[])
    for _, completo, _ in PERMISOS_ASIGNABLES:
        app, codename = completo.split(".")
        q |= Q(content_type__app_label=app, codename=codename)
    return Permission.objects.filter(q)


def nombre_completo(permiso) -> str:
    return f"{permiso.content_type.app_label}.{permiso.codename}"
