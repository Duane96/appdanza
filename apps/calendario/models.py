from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from apps.academias.models import TenantModel
from apps.profesores.models import Profesor, OrdenPagoMensual
from apps.finanzas.models import Gasto

class Clase(TenantModel):
    """
    Catálogo Base de la Clase (El concepto/temario). 
    Ej: 'Bachata Sensual', 'Salsa Casino'.
    """
    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Clase")
    descripcion = models.TextField(blank=True, null=True)
    
    # Configuraciones globales de la materia
    tarifa_especifica = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Déjalo en blanco para usar la tarifa base del profesor que la dicte.")
    color_calendario = models.CharField(max_length=7, default="#6f42c1")
    limite_cupos = models.IntegerField(default=30)
    
    def __str__(self):
        return self.nombre


class SesionClase(TenantModel):
    """
    La sesión real agendada en el calendario. 
    Aquí se define quién la da, a qué hora y qué día.
    """
    ESTADOS = [
        ('PROGRAMADA', 'Programada (Visible para reservar)'),
        ('DICTADA', 'Dictada (Check del Admin)'),
        ('CANCELADA', 'Cancelada (Feriado, ausencia, etc)'),
    ]
    
    clase = models.ForeignKey(Clase, on_delete=models.CASCADE, related_name='sesiones')
    # 🚀 AHORA EL PROFESOR SE ASIGNA AL AGENDAR LA SESIÓN
    profesor_asignado = models.ForeignKey(Profesor, on_delete=models.PROTECT, related_name='sesiones_asignadas')
    
    fecha_hora_inicio = models.DateTimeField()
    fecha_hora_fin = models.DateTimeField()
    
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PROGRAMADA')
    
    # Campos para excepciones (Override)
    profesor_reemplazo = models.ForeignKey(
        Profesor, on_delete=models.SET_NULL, blank=True, null=True, related_name='clases_reemplazo',
        help_text="Profesor invitado o reemplazo solo por este día."
    )
    notas_excepcion = models.CharField(max_length=255, blank=True, null=True)
    
    # Control financiero
    pagada_al_profesor = models.BooleanField(default=False)
    gasto_individual = models.OneToOneField(Gasto, on_delete=models.SET_NULL, blank=True, null=True)
    orden_pago_mensual = models.ForeignKey(OrdenPagoMensual, on_delete=models.SET_NULL, blank=True, null=True)

    def __str__(self):
        return f"{self.clase.nombre} | {self.fecha_hora_inicio.strftime('%d/%m %H:%M')}"

    @property
    def profe_a_pagar(self):
        # 🚀 Buscamos el reemplazo, si no hay, pagamos al profesor asignado a la sesión
        return self.profesor_reemplazo if self.profesor_reemplazo else self.profesor_asignado

    @property
    def tarifa_a_pagar(self):
        return self.clase.tarifa_especifica if self.clase.tarifa_especifica else self.profe_a_pagar.tarifa_base

    
class ReservaEstudiante(TenantModel):
    """
    Registro de cuando un estudiante le da "Reservar" en su calendario.
    """
    sesion = models.ForeignKey(SesionClase, on_delete=models.CASCADE, related_name='reservas')
    # Aquí enlazamos al User (Estudiante). Más adelante filtraremos que tenga un Plan Activo.
    estudiante = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mis_reservas')
    
    asistio = models.BooleanField(default=False, verbose_name="¿Asistió realmente a la clase?")
    fecha_reserva = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Evita que un estudiante reserve la misma sesión dos veces
        unique_together = ('sesion', 'estudiante')

    def __str__(self):
        return f"{self.estudiante.get_full_name()} -> {self.sesion}"