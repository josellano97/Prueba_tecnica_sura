"""
Autenticación (vistas nativas de Django) y administración de usuarios y roles.

Todas las vistas de administración exigen sesión y el permiso correspondiente de Django
(auth.view_user, auth.add_user, auth.change_user, auth.view_group...). Además:
* un usuario que no es superusuario no puede ver ni modificar superusuarios;
* nadie puede desactivarse a sí mismo;
* los cambios de estado se hacen solo por POST (con token CSRF).
"""
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.models import Group
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from .forms import FormularioLogin, RolForm, UsuarioForm
from .roles import DESCRIPCION_ROLES, PERMISOS_ASIGNABLES, nombre_completo

Usuario = get_user_model()
log = logging.getLogger("seguridad")


# --------------------------------------------------------------------------- autenticación
class IngresoView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = FormularioLogin
    redirect_authenticated_user = True


class SalidaView(auth_views.LogoutView):
    """Cierre de sesión (solo POST, como exige Django 5)."""


class CambioContrasenaView(auth_views.PasswordChangeView):
    template_name = "registration/cambio_contrasena.html"
    success_url = reverse_lazy("inicio")

    def form_valid(self, form):
        messages.success(self.request, "Su contraseña se actualizó correctamente.")
        return super().form_valid(form)


# --------------------------------------------------------------------------- usuarios
class _AlcanceUsuarios:
    """Un administrador que no es superusuario no ve ni edita superusuarios."""

    def get_queryset(self):
        qs = Usuario.objects.select_related("perfil__coordinador").prefetch_related("groups")
        if not self.request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        return qs


class UsuarioListaView(LoginRequiredMixin, PermissionRequiredMixin, _AlcanceUsuarios, ListView):
    permission_required = "auth.view_user"
    template_name = "cuentas/usuarios_lista.html"
    context_object_name = "usuarios"
    paginate_by = 15

    def get_queryset(self):
        qs = super().get_queryset().order_by("-is_active", "username")
        texto = self.request.GET.get("q", "").strip()
        if texto:
            qs = qs.filter(Q(username__icontains=texto) | Q(first_name__icontains=texto) |
                           Q(last_name__icontains=texto) | Q(email__icontains=texto))
        estado = self.request.GET.get("estado")
        if estado in ("activos", "inactivos"):
            qs = qs.filter(is_active=(estado == "activos"))
        rol = self.request.GET.get("rol")
        if rol and rol.isdigit():
            qs = qs.filter(groups__id=int(rol))
        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = super().get_queryset()
        ctx.update({
            "roles": Group.objects.order_by("name"),
            "filtros": {k: self.request.GET.get(k, "") for k in ("q", "estado", "rol")},
            "totales": {"todos": base.count(), "activos": base.filter(is_active=True).count()},
            "puede_crear": self.request.user.has_perm("auth.add_user"),
            "puede_editar": self.request.user.has_perm("auth.change_user"),
        })
        return ctx


class _FormularioUsuario:
    form_class = UsuarioForm
    template_name = "cuentas/usuario_form.html"
    success_url = reverse_lazy("cuentas:usuarios")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editor"] = self.request.user
        return kwargs


class UsuarioCrearView(LoginRequiredMixin, PermissionRequiredMixin, _FormularioUsuario, CreateView):
    permission_required = ("auth.view_user", "auth.add_user")

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        log.info("Usuario creado: %s por %s", self.object.username, self.request.user.username)
        messages.success(self.request, f"Usuario «{self.object.username}» creado correctamente.")
        return respuesta


class UsuarioEditarView(LoginRequiredMixin, PermissionRequiredMixin, _AlcanceUsuarios, _FormularioUsuario, UpdateView):
    permission_required = ("auth.view_user", "auth.change_user")
    context_object_name = "usuario_editado"

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        log.info("Usuario modificado: %s por %s", self.object.username, self.request.user.username)
        messages.success(self.request, f"Cambios de «{self.object.username}» guardados.")
        return respuesta


class UsuarioEstadoView(LoginRequiredMixin, PermissionRequiredMixin, _AlcanceUsuarios, View):
    """Activa o desactiva un usuario (POST). Desactivar conserva el usuario y su historial."""

    permission_required = ("auth.view_user", "auth.change_user")
    http_method_names = ["post"]

    def post(self, request, pk):
        usuario = get_object_or_404(self.get_queryset(), pk=pk)
        destino = request.POST.get("siguiente") or reverse("cuentas:usuarios")
        if not destino.startswith("/") or destino.startswith("//"):       # evita redirecciones abiertas
            destino = reverse("cuentas:usuarios")
        if usuario.pk == request.user.pk:
            messages.error(request, "No puede desactivar su propia cuenta.")
            return HttpResponseRedirect(destino)
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=["is_active"])
        estado = "activado" if usuario.is_active else "desactivado"
        log.info("Usuario %s: %s por %s", estado, usuario.username, request.user.username)
        messages.success(request, f"Usuario «{usuario.username}» {estado}.")
        return HttpResponseRedirect(destino)


# --------------------------------------------------------------------------- roles
class RolListaView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "auth.view_group"
    template_name = "cuentas/roles_lista.html"
    context_object_name = "roles"

    def get_queryset(self):
        return Group.objects.annotate(n_usuarios=Count("user", distinct=True)).prefetch_related(
            "permissions__content_type").order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        secciones = []
        for seccion, permiso, descripcion in PERMISOS_ASIGNABLES:
            if not secciones or secciones[-1]["nombre"] != seccion:
                secciones.append({"nombre": seccion, "permisos": []})
            secciones[-1]["permisos"].append({"codigo": permiso, "descripcion": descripcion})
        matriz = []
        for rol in ctx["roles"]:
            tiene = {nombre_completo(p) for p in rol.permissions.all()}
            matriz.append({"rol": rol, "descripcion": DESCRIPCION_ROLES.get(rol.name, ""),
                           "tiene": tiene})
        ctx.update({"secciones": secciones, "matriz": matriz,
                    "puede_crear": self.request.user.has_perm("auth.add_group"),
                    "puede_editar": self.request.user.has_perm("auth.change_group")})
        return ctx


class _FormularioRol:
    form_class = RolForm
    template_name = "cuentas/rol_form.html"
    success_url = reverse_lazy("cuentas:roles")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["editor"] = self.request.user
        return kwargs


class RolCrearView(LoginRequiredMixin, PermissionRequiredMixin, _FormularioRol, CreateView):
    permission_required = ("auth.view_group", "auth.add_group")

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        log.info("Rol creado: %s por %s", self.object.name, self.request.user.username)
        messages.success(self.request, f"Rol «{self.object.name}» creado.")
        return respuesta


class RolEditarView(LoginRequiredMixin, PermissionRequiredMixin, _FormularioRol, UpdateView):
    permission_required = ("auth.view_group", "auth.change_group")
    queryset = Group.objects.all()
    context_object_name = "rol"

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        log.info("Rol modificado: %s por %s", self.object.name, self.request.user.username)
        messages.success(self.request, f"Permisos del rol «{self.object.name}» actualizados.")
        return respuesta
