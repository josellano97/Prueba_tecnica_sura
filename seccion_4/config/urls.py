from django.contrib import admin
from django.urls import include, path

from apps.agente.views import ChatAgenteView
from apps.core import views as core

admin.site.site_header = "Monitoreo de siniestralidad · Administración"
admin.site.site_title = "Administración"
admin.site.index_title = "Usuarios, roles, catálogos y configuración"

urlpatterns = [
    path("", core.inicio, name="inicio"),
    path("salud/", core.salud, name="salud"),
    path("favicon.ico", core.favicon),
    path("cuentas/", include("apps.cuentas.urls")),
    path("tablero/", include("apps.tablero.urls")),
    path("analisis/", include("apps.analisis.urls")),
    path("api/agente/", include("apps.agente.urls")),
    path("agente/", ChatAgenteView.as_view(), name="agente_chat"),     # pestaña «Agente Sura»   # API de solo lectura para n8n
    path("admin/", admin.site.urls),
]

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"
