# apps/asistencias/models.py
from django.db import models
from django.contrib.auth.models import User
from apps.academias.models import TenantModel
from apps.planes_estudiantes.models import Estudiante

class Asistencia(TenantModel):
    """Registra el ingreso diario de los alumnos a sus clases."""
    TIPOS_MARCADO = (
        ('QR', 'Escaneo de Código QR'),
        ('MANUAL', 'Marcado Manual por Profesor'),
    )

    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name="asistencias")
    fecha_hora = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y Hora de Entrada")
    tipo_marcado = models.CharField(max_length=10, choices=TIPOS_MARCADO, default='QR')
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.estudiante} - {self.fecha_hora.strftime('%d/%m/%Y %H:%M')}"