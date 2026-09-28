from django.urls import path

from . import views

app_name = "agente"
urlpatterns = [
    path("resumen/", views.resumen, name="resumen"),
    path("clientes/", views.buscar_clientes, name="buscar_clientes"),
    path("clientes/<int:cliente_id>/", views.cliente, name="cliente"),
    path("criticos/", views.criticos, name="criticos"),
    path("top/", views.top, name="top"),
    path("glosario/", views.glosario, name="glosario"),
]
