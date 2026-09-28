"""
Carga los datos de demostración generados en el código y, opcionalmente, usuarios demo.

    python manage.py cargar_datos_demo                    # datos del tablero
    python manage.py cargar_datos_demo --usuarios-demo    # + un usuario por rol (contraseñas aleatorias)
    python manage.py cargar_datos_demo --reemplazar       # borra y vuelve a cargar los datos

Las contraseñas de los usuarios demo nunca están en el código: se toman de la variable DEMO_PASSWORD
o se generan al azar y se muestran una sola vez en la consola.
"""
import os
import secrets
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tablero.models import CargaDatos, Cliente, ConfiguracionTablero, Coordinador, IndicadorMensual, Sector
from apps.tablero.servicios import generador_demo

USUARIOS_DEMO = [
    # (usuario, nombres, rol, coordinador, acceso al admin)
    ("admin_demo", "Administradora Demo", "Administrador", None, True),
    ("analista_demo", "Analista Demo", "Usuario", None, False),
    ("consulta_demo", "Consulta Demo", "Consulta", None, False),
    ("coordinador_demo", "Ana Restrepo", "Coordinador", "Ana Restrepo", False),
]


def correo(nombre: str) -> str:
    base = nombre.lower().replace(" ", ".")
    for a, b in zip("áéíóúñ", "aeioun"):
        base = base.replace(a, b)
    return f"{base}@empresa-ejemplo.co"


class Command(BaseCommand):
    help = "Carga los datos de demostración del tablero y, si se pide, usuarios demo por rol."

    def add_arguments(self, parser):
        parser.add_argument("--reemplazar", action="store_true", help="Elimina los datos existentes antes de cargar.")
        parser.add_argument("--usuarios-demo", action="store_true", help="Crea un usuario de demostración por rol.")
        parser.add_argument("--fecha", type=date.fromisoformat, default=None,
                            help="Fecha de referencia AAAA-MM-DD (por defecto hoy): los 24 meses terminan el mes anterior.")

    @transaction.atomic
    def handle(self, *args, **opciones):
        if IndicadorMensual.objects.exists() and not opciones["reemplazar"]:
            self.stdout.write(self.style.WARNING("Ya hay datos cargados; use --reemplazar para volver a generarlos."))
        else:
            self._cargar_datos(opciones["fecha"])
        ConfiguracionTablero.actual()
        if opciones["usuarios_demo"]:
            crear_usuarios_demo(self, "Ana Restrepo")

    def _cargar_datos(self, fecha):
        IndicadorMensual.objects.all().delete()
        Cliente.objects.all().delete()
        datos = generador_demo.generar(fecha)
        sectores = {n: Sector.objects.get_or_create(nombre=n)[0] for n in generador_demo.SECTORES}
        coordinadores = {n: Coordinador.objects.get_or_create(nombre=n, defaults={"correo": correo(n)})[0]
                         for n in generador_demo.COORDINADORES}
        clientes = {c.id: Cliente.objects.create(nombre=c.nombre, sector=sectores[c.sector], clase_riesgo=c.clase,
                                                 coordinador=coordinadores[c.coordinador]) for c in datos.clientes}
        IndicadorMensual.objects.bulk_create([
            IndicadorMensual(cliente=clientes[h["cliente"]], periodo=h["periodo"], trabajadores_activos=h["trabajadores"],
                             casos=h["casos"], casos_graves=h["graves"],
                             costo_leve=Decimal(str(round(h["costo_leve"], 2))),
                             costo_grave=Decimal(str(round(h["costo_grave"], 2))))
            for h in datos.hechos], batch_size=1000)
        CargaDatos.objects.all().delete()
        fin = datos.meses[-1]
        CargaDatos.objects.create(
            fuente="demo", descripcion="Datos de demostración generados en el código",
            fecha_corte=date(fin.year + (fin.month == 12), fin.month % 12 + 1, 1) - timedelta(days=1),
            periodo_desde=datos.meses[0], periodo_hasta=fin, variables=[],
            calidad={"hallazgos": [{"codigo": "FUENTE_DEMO", "severidad": "info", "registros": len(datos.hechos),
                                    "descripcion": "Datos sintéticos agregados por cliente y mes, sin detalle de casos, prevención ni facturación.",
                                    "tratamiento": "Los análisis que requieren esas variables se muestran como no disponibles.",
                                    "afecta": ["severidad", "prevención", "índice de costo", "drill-down a casos"], "ejemplos": []}],
                     "resumen": {"clientes": len(clientes), "registros_mensuales": len(datos.hechos)}})
        self.stdout.write(self.style.SUCCESS(
            f"Datos cargados: {len(clientes)} clientes, {len(datos.hechos)} registros mensuales "
            f"({datos.meses[0]:%Y-%m} a {datos.meses[-1]:%Y-%m})."))



def crear_usuarios_demo(comando, coordinador: str):
    """Crea un usuario demo por rol (compartido por los dos comandos de carga)."""
    Usuario = get_user_model()
    clave_fija = os.environ.get("DEMO_PASSWORD")
    comando.stdout.write("Usuarios demo (guarde estas contraseñas; no se vuelven a mostrar):")
    for usuario, nombre, rol, coord, staff in USUARIOS_DEMO:
        try:
            grupo = Group.objects.get(name=rol)
        except Group.DoesNotExist as e:
            raise CommandError(f"No existe el rol «{rol}». Ejecute primero: python manage.py migrate") from e
        u, creado = Usuario.objects.get_or_create(username=usuario, defaults={
            "first_name": nombre.split()[0], "last_name": " ".join(nombre.split()[1:]),
            "email": f"{usuario}@empresa-ejemplo.co", "is_staff": staff})
        if coord:
            u.perfil.coordinador = Coordinador.objects.get(nombre=coordinador)
            u.perfil.save()
        if not creado:
            comando.stdout.write(f"  {usuario:<18} ya existía (no se cambió su contraseña)")
            continue
        clave = clave_fija or secrets.token_urlsafe(12)
        u.set_password(clave)
        u.save()
        u.groups.add(grupo)
        comando.stdout.write(f"  {usuario:<18} rol={rol:<14} contraseña={clave}")
