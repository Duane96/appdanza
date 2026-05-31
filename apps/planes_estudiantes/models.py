# apps/planes_estudiantes/models.py
import qrcode
import uuid
from io import BytesIO
from django.core.files import File
from django.db import models
from django.utils import timezone
from apps.academias.models import TenantModel  # Heredamos de nuestro cascarón aislado

class Plan(TenantModel):
    """Membresías o tiqueteras que vende cada academia de forma independiente."""
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Plan")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    precio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio ($ COP)")
    duracion_dias = models.PositiveIntegerField(default=30, verbose_name="Duración en Días")
    clases_totales = models.PositiveIntegerField(default=8, verbose_name="Clases Incluidas")

    def __str__(self):
        return f"{self.nombre} - ${self.precio:,.0f} COP"


class Estudiante(TenantModel):
    """Base de datos de alumnos de la academia."""
    ESTADOS = (
        ('ACTIVO', 'Activo / Al Día'),
        ('INACTIVO', 'Inactivo / Sin Plan'),
    )
    
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    identificacion = models.CharField(max_length=20, unique=True, verbose_name="Cédula / TI")
    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    estado = models.CharField(max_length=15, choices=ESTADOS, default='INACTIVO')
    
    # Manejo de QR físico en disco
    qr_code = models.ImageField(upload_to="qrs_estudiantes/", blank=True, null=True)
    token_asistencia = models.CharField(max_length=64, unique=True, editable=False, null=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombres} {self.apellidos}"

    def save(self, *args, **kwargs):
        """Genera automáticamente el Token de seguridad y el código QR en el primer guardado."""
        if not self.token_asistencia:
            self.token_asistencia = uuid.uuid4().hex

        if not self.qr_code:
            # Configuración del código QR
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(self.token_asistencia)
            qr.make(fit=True)

            # Crear la imagen en memoria usando BytesIO
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            
            # Guardar el archivo en el ImageField sin registrar doble save()
            filename = f"qr_{self.identificacion}_{self.token_asistencia[:8]}.png"
            self.qr_code.save(filename, File(buffer), save=False)

        super().save(*args, **kwargs)


class InscripcionPlan(TenantModel):
    """Registro de compras de planes por estudiante."""
    estudiante = models.ForeignKey(Estudiante, on_delete=models.CASCADE, related_name="inscripciones")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="inscripciones")
    fecha_inicio = models.DateField(default=timezone.now)
    fecha_fin = models.DateField()
    clases_restantes = models.PositiveIntegerField()
    saldo_pendiente = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.estudiante} - {self.plan.nombre}"