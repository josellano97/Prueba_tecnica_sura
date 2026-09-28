from django.contrib import admin

from .models import TokenAgente


@admin.register(TokenAgente)
class TokenAgenteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "usuario", "activo", "creado", "ultimo_uso")
    list_filter = ("activo",)
    readonly_fields = ("huella", "creado", "ultimo_uso")
    # los tokens se crean con: python manage.py crear_token_agente (así el token en claro se ve una sola vez)

    def has_add_permission(self, request):
        return False
