"""
Carga la fuente oficial del proyecto (datos/salida/*.csv), la misma del SQL y el Power BI.

    python manage.py cargar_datos_proyecto                          # usa ../datos/salida
    python manage.py cargar_datos_proyecto --origen RUTA            # otra carpeta
    python manage.py cargar_datos_proyecto --usuarios-demo          # + un usuario por rol
    python manage.py cargar_datos_proyecto --solo-si-vacia          # no toca una base que ya tiene datos

Reemplaza los datos existentes (tablero y análisis) y registra la revisión de calidad de la carga.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.tablero.management.commands.cargar_datos_demo import crear_usuarios_demo
from apps.tablero.models import ConfiguracionTablero, IndicadorMensual
from apps.tablero.servicios.carga_proyecto import ErrorCarga, cargar


class Command(BaseCommand):
    help = "Carga los datos del proyecto (casos, facturación, prevención) y revisa su calidad."

    def add_arguments(self, parser):
        parser.add_argument("--origen", type=Path, default=Path(settings.BASE_DIR).parent / "datos" / "salida")
        parser.add_argument("--usuarios-demo", action="store_true")
        parser.add_argument("--solo-si-vacia", action="store_true",
                            help="Solo carga si la base no tiene datos (útil al publicar: no reemplaza lo existente).")

    def handle(self, *args, **opciones):
        if opciones["solo_si_vacia"] and IndicadorMensual.objects.exists():
            self.stdout.write("La base ya tiene datos; no se cargó nada (--solo-si-vacia).")
            return
        try:
            carga = cargar(opciones["origen"])
        except ErrorCarga as e:
            raise CommandError(str(e)) from e
        ConfiguracionTablero.actual()
        r = carga.calidad["resumen"]
        self.stdout.write(self.style.SUCCESS(
            f"Carga '{carga.fuente}': {r['clientes']} clientes, {r['registros_mensuales']} registros mensuales "
            f"({carga.periodo_desde:%Y-%m} a {carga.periodo_hasta:%Y-%m}), corte {carga.fecha_corte:%d/%m/%Y}."))
        for hz in carga.calidad["hallazgos"]:
            self.stdout.write(f"  [{hz['severidad']:<11}] {hz['codigo']:<24} {hz['registros']:>6}  {hz['tratamiento']}")
        if opciones["usuarios_demo"]:
            crear_usuarios_demo(self, "Coordinador 01")
