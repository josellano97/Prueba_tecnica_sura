"""Menú lateral construido según los permisos del usuario (el control real está en cada vista)."""
from django.urls import reverse

MENU = [
    # (clave, etiqueta, nombre de URL, permiso requerido, icono)
    ("analisis", "Análisis gerencial", "analisis:resumen", "tablero.ver_analisis", "brujula"),
    ("tablero", "Tablero", "tablero:inicio", "tablero.ver_tablero", "grafico"),
    ("calidad", "Calidad de datos", "analisis:calidad", "tablero.ver_calidad_datos", "lupa"),
    ("usuarios", "Usuarios", "cuentas:usuarios", "auth.view_user", "usuarios"),
    ("roles", "Roles y permisos", "cuentas:roles", "auth.view_group", "escudo"),
]


def navegacion(request):
    usuario = getattr(request, "user", None)
    if not usuario or not usuario.is_authenticated:
        return {}
    ruta = request.path
    asistente = _asistente(usuario)
    items = []
    for clave, etiqueta, url, permiso, icono in MENU:
        if usuario.has_perm(permiso):
            destino = reverse(url)
            activo = ruta.startswith(destino) and not (clave == "analisis" and ruta.startswith(destino + "calidad"))
            items.append({"clave": clave, "etiqueta": etiqueta, "url": destino, "icono": icono, "activo": activo})
    if asistente:                                            # pestaña «Agente Sura», siempre la última
        destino = reverse("agente_chat")
        items.append({"clave": "agente", "etiqueta": "Agente Sura", "url": destino, "icono": "chat",
                      "activo": ruta.startswith(destino)})
    return {
        "menu_items": items,
        "puede_admin": usuario.is_staff,
        "carga_datos": _carga_vigente,
        "roles_usuario": ", ".join(g.name for g in usuario.groups.all()) or ("Superusuario" if usuario.is_superuser else "Sin rol"),
        "asistente": asistente,
    }


def _asistente(usuario):
    """Datos para el chat del agente, solo si está configurado y el usuario puede ver toda la cartera."""
    from django.conf import settings
    if not (settings.AGENTE_CHAT_URL and settings.AGENTE_CHAT_USUARIO and settings.AGENTE_CHAT_CLAVE):
        return None
    if not (usuario.has_perm("tablero.ver_analisis") and usuario.has_perm("tablero.ver_todos_los_clientes")):
        return None
    import base64
    credencial = base64.b64encode(f"{settings.AGENTE_CHAT_USUARIO}:{settings.AGENTE_CHAT_CLAVE}".encode()).decode()
    return {"url": settings.AGENTE_CHAT_URL, "autorizacion": f"Basic {credencial}"}


def _carga_vigente():
    # se evalúa solo si la plantilla lo usa (pie de página)
    from apps.tablero.models import CargaDatos
    return CargaDatos.vigente()
