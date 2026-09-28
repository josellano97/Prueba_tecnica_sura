"""
Modelos del tablero de monitoreo.

Grano de los datos: un registro por cliente y mes (IndicadorMensual), el mismo que usaba el
tablero HTML original. Los permisos de negocio de la aplicación se declaran aquí (Meta.permissions)
y se asignan a los roles (Groups) desde la interfaz o el admin: el código nunca pregunta por el
nombre de un rol, solo por permisos.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Sector(models.Model):
    nombre = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "sectores"

    def __str__(self):
        return self.nombre


class Coordinador(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    correo = models.EmailField(blank=True)
    regional = models.CharField(max_length=80, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "coordinadores"

    def __str__(self):
        return self.nombre


class Cliente(models.Model):
    nombre = models.CharField(max_length=160, unique=True)
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT, related_name="clientes")
    clase_riesgo = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)],
                                                    help_text="1 = menor riesgo, 5 = mayor riesgo")
    coordinador = models.ForeignKey(Coordinador, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="clientes")
    activo = models.BooleanField(default=True)
    fecha_vinculacion = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [models.CheckConstraint(condition=Q(clase_riesgo__gte=1, clase_riesgo__lte=5),
                                              name="cliente_clase_riesgo_1_5")]

    def __str__(self):
        return self.nombre


class IndicadorMensual(models.Model):
    """Casos, costo y exposición de un cliente en un mes cerrado."""

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="indicadores")
    periodo = models.DateField(help_text="Primer día del mes")
    trabajadores_activos = models.PositiveIntegerField()
    casos = models.PositiveIntegerField(default=0)
    casos_graves = models.PositiveIntegerField(default=0)
    costo_leve = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    costo_grave = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # Variables opcionales: existen en la fuente del proyecto (datos/salida), no en los datos demo.
    # NULL significa "la fuente no trae este dato" (distinto de 0), y el análisis lo informa.
    dias_ausencia = models.PositiveIntegerField(null=True, blank=True)
    casos_abiertos = models.PositiveIntegerField(null=True, blank=True, help_text="De los casos del mes, cuántos siguen abiertos a la fecha de corte")
    casos_graves_abiertos = models.PositiveIntegerField(null=True, blank=True)
    casos_anulados = models.PositiveIntegerField(null=True, blank=True, help_text="Registros anulados (no cuentan como casos)")
    actividades_prevencion = models.PositiveIntegerField(null=True, blank=True)
    participantes_prevencion = models.PositiveIntegerField(null=True, blank=True)
    valor_contrato = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["periodo", "cliente"]
        verbose_name = "indicador mensual"
        verbose_name_plural = "indicadores mensuales"
        constraints = [
            models.UniqueConstraint(fields=["cliente", "periodo"], name="indicador_unico_cliente_periodo"),
            models.CheckConstraint(condition=Q(casos_graves__lte=F("casos")), name="indicador_graves_menor_igual_casos"),
            models.CheckConstraint(condition=Q(trabajadores_activos__gt=0), name="indicador_trabajadores_positivos"),
        ]
        indexes = [models.Index(fields=["periodo"])]
        permissions = [
            ("ver_tablero", "Puede ver el tablero de monitoreo"),
            ("ver_todos_los_clientes", "Puede ver todos los clientes (sin restricción por coordinador)"),
            ("exportar_datos", "Puede exportar datos del tablero"),
            ("ver_analisis", "Puede ver el análisis gerencial y el diagnóstico"),
            ("ver_calidad_datos", "Puede ver el reporte de calidad de datos"),
        ]

    def clean(self):
        if self.periodo and self.periodo.day != 1:
            raise ValidationError({"periodo": "El periodo debe ser el primer día del mes."})

    @property
    def costo(self):
        return self.costo_leve + self.costo_grave

    def __str__(self):
        return f"{self.cliente} · {self.periodo:%Y-%m}"


class ConfiguracionTablero(models.Model):
    """Parámetros de negocio editables por el administrador (registro único)."""

    nombre_organizacion = models.CharField(max_length=120, default="Grupo SURA")
    umbral_critico = models.DecimalField(max_digits=5, decimal_places=2, default=5,
                                         help_text="Tasa por 100 trabajadores por encima de la cual un cliente es crítico")
    umbral_moderado = models.DecimalField(max_digits=5, decimal_places=2, default=2,
                                          help_text="Tasa desde la cual un cliente es moderado (hasta el umbral crítico)")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuración del tablero"
        verbose_name_plural = "configuración del tablero"

    def __str__(self):
        return "Configuración del tablero"

    def clean(self):
        if self.umbral_moderado is not None and self.umbral_critico is not None and self.umbral_moderado >= self.umbral_critico:
            raise ValidationError("El umbral moderado debe ser menor que el umbral crítico.")

    def save(self, *args, **kwargs):
        self.pk = 1  # registro único
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # no se permite borrar la configuración
        return None

    @classmethod
    def actual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Caso(models.Model):
    """Detalle de cada incidente (solo con la fuente del proyecto). Se usa para el último nivel del drill-down."""

    TIPOS = [("leve", "Leve"), ("grave", "Grave")]
    ESTADOS = [("abierto", "Abierto"), ("cerrado", "Cerrado"), ("anulado", "Anulado")]
    id_origen = models.PositiveIntegerField(unique=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="casos")
    fecha = models.DateField()
    tipo = models.CharField(max_length=10, choices=TIPOS)
    dias_ausencia = models.PositiveIntegerField()
    costo = models.DecimalField(max_digits=14, decimal_places=2)
    estado = models.CharField(max_length=10, choices=ESTADOS)

    class Meta:
        ordering = ["-fecha"]
        indexes = [models.Index(fields=["cliente", "fecha"])]

    def __str__(self):
        return f"Caso {self.id_origen} · {self.cliente} · {self.fecha:%d/%m/%Y}"


class CargaDatos(models.Model):
    """Registro de cada carga: de dónde vienen los datos, hasta qué fecha y qué calidad tenían."""

    fuente = models.CharField(max_length=40)
    descripcion = models.CharField(max_length=200)
    fecha_corte = models.DateField(help_text="Último día con datos en la fuente")
    periodo_desde = models.DateField()
    periodo_hasta = models.DateField(help_text="Último mes cerrado cargado")
    creada = models.DateTimeField(auto_now_add=True)
    variables = models.JSONField(default=list, help_text="Variables opcionales disponibles en esta carga")
    calidad = models.JSONField(default=dict, help_text="Hallazgos de calidad detectados al cargar")

    class Meta:
        ordering = ["-creada"]
        verbose_name = "carga de datos"
        verbose_name_plural = "cargas de datos"

    def __str__(self):
        return f"{self.fuente} · corte {self.fecha_corte:%d/%m/%Y}"

    @classmethod
    def vigente(cls):
        return cls.objects.first()
