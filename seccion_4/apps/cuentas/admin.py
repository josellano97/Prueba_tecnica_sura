"""
Admin de Django: usuarios con su perfil (coordinador) en la misma pantalla.

Protección contra escalamiento en el admin: si quien edita no es superusuario, no ve superusuarios
y no puede cambiar is_superuser, is_staff, grupos ni permisos (eso se gestiona en la aplicación,
donde se valida que solo otorgue permisos que ya tiene).
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

from .models import Perfil

Usuario = get_user_model()
CAMPOS_PRIVILEGIO = ("is_superuser", "is_staff", "groups", "user_permissions")


class PerfilInline(admin.StackedInline):
    model = Perfil
    can_delete = False
    verbose_name_plural = "Perfil (alcance de datos)"


admin.site.unregister(Usuario)
admin.site.unregister(Group)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    inlines = [PerfilInline]
    list_display = ["username", "email", "first_name", "last_name", "is_active", "is_staff", "roles"]
    list_filter = ["is_active", "is_staff", "is_superuser", "groups"]

    @admin.display(description="Roles")
    def roles(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(is_superuser=False)

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        return base if request.user.is_superuser else base + list(CAMPOS_PRIVILEGIO)


@admin.register(Group)
class RolAdmin(GroupAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [] if request.user.is_superuser else ["permissions"]
