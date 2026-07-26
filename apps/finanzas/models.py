# apps/finanzas/models.py
from django.db import models
from django.utils import timezone # 🕒 Importación vital para la hora local (Colombia)
from apps.academias.models import Academia
from apps.planes_estudiantes.models import InscripcionPlan
from django.contrib.auth.models import User

from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os

class ReciboIngreso(models.Model):
    TIPOS_INGRESO = [
        ('PLAN_ESTUDIANTE', 'Pago de Plan / Tiquetera / Mensualidad'),
        ('TIENDA', 'Venta de Productos (Agua, Ropa, etc.)'),
        ('EVENTO', 'Venta de Boletas / Inscripción a Eventos'),
        ('OTROS', 'Otros Ingresos / Arriendos de Salón'),
    ]

    MEDIOS_PAGO = [
        ('EFECTIVO', 'Efectivo'),
        ('TRANSFERENCIA', 'Transferencia (Nequi/Daviplata/Bancolombia)'),
        ('TARJETA', 'Tarjeta de Crédito / Débito'),
    ]

    ESTADOS_RECIBO = [
        ('ACTIVO', 'Válido / Activo'),
        ('ANULADO', 'Anulado / Sin Efecto Contable'),
    ]

    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='ingresos')
    
    # 🔗 Enlace opcional: Si el ingreso viene de un plan, se amarra. Si es venta de agua, queda en null.
    inscripcion = models.OneToOneField(InscripcionPlan, on_delete=models.SET_NULL, blank=True, null=True, related_name='recibo_caja')
    
    # 📝 CONSECUTIVO AUTOMÁTICO INDEPENDIENTE POR ACADEMIA
    numero_recibo = models.CharField(max_length=50, editable=False, help_text="Consecutivo automático (Ej: RC-0001)")
    
    tipo_ingreso = models.CharField(max_length=50, choices=TIPOS_INGRESO, default='PLAN_ESTUDIANTE')
    concepto = models.CharField(max_length=255, help_text="Detalle (Ej: Venta de Camiseta Oficial o Pago Mes Luis Pérez)")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    medio_pago = models.CharField(max_length=50, choices=MEDIOS_PAGO, default='EFECTIVO')
    
    # 🏢 DATOS FISCALES DEL CLIENTE (Para Medios Magnéticos DIAN)
    cliente_nit = models.CharField(max_length=50, help_text="Cédula o NIT de quien paga")
    cliente_nombre = models.CharField(max_length=255, help_text="Nombre de quien realiza el pago")
    
    # 🚫 CONTROL DE ANULACIONES
    estado = models.CharField(max_length=20, choices=ESTADOS_RECIBO, default='ACTIVO')
    motivo_anulacion = models.TextField(blank=True, null=True, help_text="Por qué se anuló este recibo de caja")
    anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='recibos_anulados')
    
    # 🕒 HORA COLOMBIA: Usamos timezone.now como default en lugar de auto_now_add
    fecha = models.DateField(default=timezone.now)
    creado_en = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        """Generador de consecutivo automático seguro para Recibos (RC)"""
        if not self.numero_recibo:
            # Buscamos el último RECIBO creado por esta academia, ordenado por ID descendente
            # Usamos -id porque es más rápido a nivel SQL (ORDER BY id DESC LIMIT 1)
            ultimo_recibo = ReciboIngreso.objects.filter(academia=self.academia).order_by('-id').first()
            
            if ultimo_recibo and ultimo_recibo.numero_recibo.startswith('RC-'):
                try:
                    # Extraemos la parte numérica (ej: de "RC-0005" sacamos 5) y le sumamos 1
                    ultimo_numero = int(ultimo_recibo.numero_recibo.split('-')[1])
                    nuevo_numero = ultimo_numero + 1
                except ValueError:
                    nuevo_numero = 1
            else:
                nuevo_numero = 1
            
            # Formateamos con 4 ceros a la izquierda
            self.numero_recibo = f"RC-{nuevo_numero:04d}"
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_recibo} ({self.estado}) | {self.cliente_nombre} - ${self.monto:,.0f}"


class Gasto(models.Model):
    CATEGORIAS_GASTO = [
        ('NOMINA', 'Pago de Profesores / Nómina (Sueldo)'),
        ('ARRIENDO', 'Arriendo de Sede / Soportes'),
        ('SERVICIOS', 'Servicios Públicos (Agua, Luz, Internet)'),
        ('MARKETING', 'Publicidad y Marketing'),
        ('EQUIPOS', 'Mantenimiento o Equipos del salón'),
        ('OTROS', 'Otros Egresos / Imprevistos'),
    ]

    ESTADOS_GASTO = [
        ('ACTIVO', 'Válido / Activo'),
        ('ANULADO', 'Anulado'),
    ]

    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='gastos')
    
    # 📝 CONSECUTIVO AUTOMÁTICO DE EGRESO
    numero_egreso = models.CharField(max_length=50, editable=False, help_text="Consecutivo automático (Ej: CE-0001)")
    
    # 🧾 NÚMERO DE FACTURA EXTERNA
    numero_factura_proveedor = models.CharField(max_length=100, blank=True, null=True, help_text="Número de la factura que te dio el proveedor")
    
    categoria = models.CharField(max_length=50, choices=CATEGORIAS_GASTO, default='OTROS')
    concepto = models.CharField(max_length=255, help_text="Ej: Pago de 4 clases de Salsa dictadas por el Prof. Carlos")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    
    # 🕒 HORA COLOMBIA
    fecha = models.DateField(default=timezone.now, help_text="Fecha real del gasto o pago")
    
    # 🏢 DATOS DE A QUIÉN LE PAGAMOS
    proveedor_nit = models.CharField(max_length=50, help_text="Cédula o NIT del tercero que recibe el dinero")
    proveedor_nombre = models.CharField(max_length=255, help_text="Nombre o Razón Social del tercero")
    
    # 📎 ARCHIVO DE SOPORTE FÍSICO
    soporte_digital = models.FileField(
        upload_to='soportes_gastos/', 
        blank=True, 
        null=True, 
        help_text="PDF o Foto de la tirilla o factura. (Opcional)"
    )

    # 🚫 CONTROL DE ANULACIONES
    estado = models.CharField(max_length=20, choices=ESTADOS_GASTO, default='ACTIVO')
    motivo_anulacion = models.TextField(blank=True, null=True, help_text="Por qué se anuló este egreso")
    anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='gastos_anulados')
    
    # 🕒 HORA COLOMBIA
    creado_en = models.DateTimeField(default=timezone.now)

    es_deducible = models.BooleanField(
        default=True, 
        help_text="¿Este gasto cuenta con soporte válido para deducir impuestos (DIAN)?"
    )

    def save(self, *args, **kwargs):
        """Generador de consecutivo automático seguro y optimización de soportes (CE)"""
        
        # 1. Consecutivo automático seguro
        if not self.numero_egreso:
            ultimo_gasto = Gasto.objects.filter(academia=self.academia).order_by('-id').first()
            
            if ultimo_gasto and ultimo_gasto.numero_egreso.startswith('CE-'):
                try:
                    ultimo_numero = int(ultimo_gasto.numero_egreso.split('-')[1])
                    nuevo_numero = ultimo_numero + 1
                except ValueError:
                    nuevo_numero = 1
            else:
                nuevo_numero = 1
                
            self.numero_egreso = f"CE-{nuevo_numero:04d}"
            
        # 2. ⚡ Optimización del Soporte Digital a WebP (Baja Resolución)
        if self.soporte_digital and not self.soporte_digital.name.lower().endswith('.webp'):
            try:
                img = Image.open(self.soporte_digital)
                
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img.thumbnail((1200, 1200))
                
                output = BytesIO()
                img.save(output, format='WEBP', quality=65) 
                output.seek(0)
                
                base_name = os.path.splitext(os.path.basename(self.soporte_digital.name))[0]
                nuevo_nombre = f"{base_name}_optimizado.webp"
                
                self.soporte_digital.save(nuevo_nombre, ContentFile(output.read()), save=False)
            except Exception as e:
                print(f"No se pudo convertir a WebP (Probablemente sea un PDF o archivo corrupto): {e}")

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_egreso} ({self.estado}) | {self.proveedor_nombre} - ${self.monto:,.0f}"