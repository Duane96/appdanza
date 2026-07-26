from django.db import models
from django.contrib.auth.models import User
from apps.academias.models import TenantModel
from apps.finanzas.models import Gasto

class Profesor(TenantModel):
    """
    Perfil extendido para el rol PROFESOR.
    """
    TIPO_PAGO_CHOICES = [
        ('POR_CLASE', 'Pago individual por clase dictada'),
        ('MENSUAL', 'Pago mensual acumulado (Planilla / Orden de Pago)'),
    ]
    
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_profesor')
    
    # NUEVO CAMPO: Vital para cruzar con Finanzas (DIAN) y usarlo como password
    documento_identidad = models.CharField(
        max_length=50, 
        verbose_name="Documento de Identidad / NIT",
        help_text="Se usará como contraseña inicial y para soportes de egreso."
    )
    
    telefono = models.CharField(max_length=20)
    tipo_pago = models.CharField(max_length=20, choices=TIPO_PAGO_CHOICES, default='POR_CLASE')
    tarifa_base = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Tarifa base por clase"
    )
    activo = models.BooleanField(default=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.get_full_name()} - {self.documento_identidad}"


class OrdenPagoMensual(TenantModel):
    """
    Planilla de pago generada automáticamente para los profesores con cobro MENSUAL.
    El profesor la revisa, la aprueba y el admin la paga.
    """
    ESTADOS_ORDEN = [
        ('GENERADA', 'Generada (Pendiente revisión del profesor)'),
        ('REVISAR', 'En revisión (El profesor dejó comentarios)'),
        ('APROBADA_PROFE', 'Aprobada por el profe (Lista para que Admin pague)'),
        ('PAGADA', 'Pagada e ingresada en Finanzas'),
    ]
    
    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name='ordenes_pago')
    mes_periodo = models.DateField(help_text="Mes de referencia (Ej: 2026-07-01 representa Julio)")
    
    cantidad_clases = models.IntegerField(default=0, verbose_name="Total clases dictadas")
    monto_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    estado = models.CharField(max_length=25, choices=ESTADOS_ORDEN, default='GENERADA')
    comentarios_profe = models.TextField(
        blank=True, 
        null=True, 
        help_text="Observaciones si el profesor le da clic a 'Revisar'"
    )
    
    # 🔗 Enlace directo al módulo de finanzas cuando la academia le da "Pagar"
    gasto_asociado = models.OneToOneField(
        Gasto, 
        on_delete=models.SET_NULL, 
        blank=True, 
        null=True, 
        related_name='orden_pago_profe'
    )
    
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    

    def __str__(self):
        return f"Planilla {self.profesor.usuario.first_name} - {self.mes_periodo.strftime('%b %Y')}"