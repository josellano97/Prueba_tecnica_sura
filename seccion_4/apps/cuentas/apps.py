from django.apps import AppConfig


class CuentasConfig(AppConfig):
    name = "apps.cuentas"
    verbose_name = "Cuentas y accesos"

    def ready(self):
        from . import signals  # noqa: F401  (registra señales de perfil y auditoría)
