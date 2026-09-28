from django.urls import path

from . import views

app_name = "cuentas"
urlpatterns = [
    path("ingresar/", views.IngresoView.as_view(), name="login"),
    path("salir/", views.SalidaView.as_view(), name="logout"),
    path("contrasena/", views.CambioContrasenaView.as_view(), name="cambio_contrasena"),
    path("usuarios/", views.UsuarioListaView.as_view(), name="usuarios"),
    path("usuarios/nuevo/", views.UsuarioCrearView.as_view(), name="usuario_crear"),
    path("usuarios/<int:pk>/", views.UsuarioEditarView.as_view(), name="usuario_editar"),
    path("usuarios/<int:pk>/estado/", views.UsuarioEstadoView.as_view(), name="usuario_estado"),
    path("roles/", views.RolListaView.as_view(), name="roles"),
    path("roles/nuevo/", views.RolCrearView.as_view(), name="rol_crear"),
    path("roles/<int:pk>/", views.RolEditarView.as_view(), name="rol_editar"),
]
