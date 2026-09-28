from django.urls import path

from . import views

app_name = "tablero"
urlpatterns = [
    path("", views.TableroView.as_view(), name="inicio"),
    path("api/datos/", views.DatosTableroView.as_view(), name="datos"),
    path("configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("exportar/top10.csv", views.ExportarTopView.as_view(), name="exportar_top"),
]
