from django.contrib import admin

from .models import Cliente, ConfiguracionTablero, Coordinador, IndicadorMensual, Sector


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    search_fields = ["nombre"]


@admin.register(Coordinador)
class CoordinadorAdmin(admin.ModelAdmin):
    list_display = ["nombre", "correo", "activo"]
    list_filter = ["activo"]
    search_fields = ["nombre", "correo"]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "sector", "clase_riesgo", "coordinador", "activo"]
    list_filter = ["activo", "clase_riesgo", "sector", "coordinador"]
    search_fields = ["nombre"]
    list_select_related = ["sector", "coordinador"]


@admin.register(IndicadorMensual)
class IndicadorMensualAdmin(admin.ModelAdmin):
    list_display = ["cliente", "periodo", "trabajadores_activos", "casos", "casos_graves", "costo_leve", "costo_grave"]
    list_filter = ["periodo", "cliente__sector"]
    search_fields = ["cliente__nombre"]
    date_hierarchy = "periodo"
    list_select_related = ["cliente"]


@admin.register(ConfiguracionTablero)
class ConfiguracionTableroAdmin(admin.ModelAdmin):
    list_display = ["nombre_organizacion", "umbral_moderado", "umbral_critico", "actualizado"]

    def has_add_permission(self, request):          # registro único
        return not ConfiguracionTablero.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
