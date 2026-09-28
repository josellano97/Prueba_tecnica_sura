from django.urls import path

from . import views

app_name = "analisis"
urlpatterns = [
    path("", views.ResumenView.as_view(), name="resumen"),
    path("diagnostico/", views.DiagnosticoView.as_view(), name="diagnostico"),
    path("calidad/", views.CalidadView.as_view(), name="calidad"),
    path("metodologia/", views.MetodologiaView.as_view(), name="metodologia"),
]
