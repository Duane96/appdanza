from apps.academias.scoped_model import ScopedModel
from apps.academias.private_media import private_storage, validate_private_upload
# apps/eventos/models.py
import uuid
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from apps.academias.models import Academia
import os


from django.utils.text import slugify
from io import BytesIO  # O simplemente 'from io import BytesIO'
from django.core.files.base import ContentFile
from PIL import Image

from apps.academias.models import TenantModel
from django.db.models.functions import Coalesce
from django.db.models import F, Sum


def ruta_banners_academia(instance, filename):
    """
    Genera una ruta de almacenamiento aislada por cada academia.
    Ejemplo de salida: logos_academias/academia-salsa/banners/mi_afiche.png
    """
    # Obtenemos el slug único de la academia vinculada al evento
    slug_academia = instance.academia.slug
    # Retornamos la estructura limpia de directorios
    return os.path.join('logos_academias', slug_academia, 'banners', filename)

class Evento(TenantModel):
    connect_dya_finances = models.BooleanField(default=False, verbose_name='Conectar con finanzas Duane y Aleja')
    updated_at = models.DateTimeField(auto_now=True)

    ESTADOS = (
        ('REGISTRO_ONLINE', 'Registro Online Abierto'),
        ('REGISTRO_PUERTA', 'Solo Registro en Puerta'),
        ('FINALIZADO', 'Evento Finalizado y Cerrado'),
    )
    
    academia = models.ForeignKey('academias.Academia', on_delete=models.CASCADE, related_name='eventos_academia')
    nombre = models.CharField(max_length=200)
    slug = models.SlugField(max_length=250)
    fecha = models.DateTimeField()
    ubicacion = models.CharField(max_length=255)
    
    precio_preventa = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    precio_puerta = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    
    # 🏦 CANALES ESTRUCTURADOS DE RECAUDO PROPIO DE LA ACADEMIA
    acepta_nequi_daviplata = models.BooleanField(default=False, verbose_name="Habilitar Nequi/Daviplata/Llave")
    numero_nequi_daviplata = models.CharField(max_length=100, blank=True, null=True, verbose_name="Número o Texto de la Llave")
    
    acepta_banco_manual = models.BooleanField(default=False, verbose_name="Habilitar Transferencia Bancaria Directa")
    datos_banco_manual = models.TextField(blank=True, null=True, help_text="Inyecta: Banco, Tipo de cuenta, Número, Cédula/NIT titular.")
    
    acepta_tarjetas_online = models.BooleanField(default=False, verbose_name="Habilitar Pago Automático con Tarjeta")

    terminos_condiciones = models.TextField(
        default="Al adquirir esta entrada aceptas las políticas de ingreso de la academia. No se realizan devoluciones."
    )
    
    estado = models.CharField(max_length=20, choices=ESTADOS, default='REGISTRO_ONLINE')
    creado_en = models.DateTimeField(auto_now_add=True)
    imagen = models.ImageField(upload_to=ruta_banners_academia, blank=True, null=True)

    # 📊 AUDITORÍA Y TRAZABILIDAD DE DEUDA CON TEMPO HUB
    online_liquidado = models.BooleanField(default=False, verbose_name="¿Comisión Online Pagada a la Plataforma?")
    puerta_liquidado = models.BooleanField(default=False, verbose_name="¿Comisión Puerta Pagada a la Plataforma?")
    
    deuda_online_calculada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    deuda_puerta_calculada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    es_multidias = models.BooleanField(default=False, verbose_name="¿Es un evento de varios días?")
    fecha_fin = models.DateTimeField(null=True, blank=True)
    cantidad_dias = models.PositiveIntegerField(default=1, help_text="Total de días del evento")
    
    # Nuevo: Permitir compra por día individual
    permite_compra_por_dia = models.BooleanField(default=False)
    precio_por_dia = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    # 🚀 NUEVOS SWITCHES DE ARQUITECTURA
    tiene_pases_personalizados = models.BooleanField(default=False, verbose_name="¿Tiene varios tipos de entrada/pases?")
    tiene_fases_fechas = models.BooleanField(default=False, verbose_name="¿Tiene múltiples fechas de pago (Preventas)?")

    # 🚀 NUEVO: Campo para URLs externas (Ticketera, Web propia, Google Form, etc.)
    enlace_externo = models.URLField(
        max_length=500, 
        blank=True, 
        null=True, 
        verbose_name="Enlace de Registro Externo",
        help_text="Si se llena, el botón 'Conseguir Tickets' abrirá esta URL en otra pestaña."
    )

    # 🚀 NUEVO: Mapeo de Ciudades Estandarizadas (Idéntico a Academias)
    CIUDADES_CHOICES = [
        ('Bogotá', 'Bogotá'),
        ('Medellín', 'Medellín'),
        ('Cali', 'Cali'),
        ('Barranquilla', 'Barranquilla'),
        ('Bucaramanga', 'Bucaramanga'),
        ('Pereira', 'Pereira'),
        ('Manizales', 'Manizales'),
        ('Armenia', 'Armenia'),
        ('Cartagena', 'Cartagena'),
        ('Villavicencio', 'Villavicencio'),
        ('Ibagué', 'Ibagué'),
        ('Otra', 'Otra ciudad...'),
    ]

    # 🚀 REFACTOR SENIOR: Ciudad controlada con Choices y default seguro
    ciudad = models.CharField(
        max_length=50, 
        choices=CIUDADES_CHOICES, 
        default='Bogotá', 
        blank=True, 
        null=True, 
        verbose_name="Ciudad del Evento",
        help_text="Selecciona la ciudad física del evento. Si se deja en blanco, heredará la de tu academia."
    )

    class Meta:
        unique_together = ('academia', 'slug')
        ordering = ['-fecha']

    # 🧠 MÉTODO SENIOR: Cómputo de Deudas Dinámicas con Reglas de País
    # 🧠 MÉTODO SENIOR: Cómputo de Deudas Dinámicas con Reglas de País
    def calcular_estado_comisiones(self):
        from .legacy_fees import statement
        return statement(self)

    def __str__(self):
        return f"{self.nombre} ({self.academia.nombre})"

    # 🧠 NUEVO MÉTODO SENIOR: Congelar deuda y cerrar
    def congelar_deuda_y_finalizar(self):
        # Closing sales does not invent or recompute historical SaaS debt.
        self.estado = 'FINALIZADO'
        self.save(update_fields=['estado'])

    def save(self, *args, **kwargs):
        # 1. Aseguramos el slug antes de guardar
        if not self.slug:
            self.slug = slugify(self.nombre)

        # 🚀 REFACTOR SENIOR: Auto-completar ciudad inteligentemente.
        # Si la ciudad viene vacía, intentamos heredar la de la academia. 
        # Si la academia no tiene, forzamos 'Bogotá'.
        if not self.ciudad:
            if self.academia and getattr(self.academia, 'ciudad', None):
                self.ciudad = self.academia.ciudad
            else:
                self.ciudad = 'Bogotá'

        # 2. PROCESAMIENTO INTELIGENTE DE IMAGEN A WEBP
        # Si el usuario subió una imagen nueva y esta no ha sido procesada aún
        if self.imagen and not self.imagen.name.endswith('.webp'):
            try:
                # Abrimos la imagen original (sea JPG, PNG, etc.) usando Pillow
                img = Image.open(self.imagen)
                
                # Convertimos a formato RGB si viene en RGBA (como algunos PNG transparentes)
                # ya que WebP estándar requiere canales definidos o fondo sólido para comprimir bien
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                    img = background
                
                # Creamos un buffer temporal en la memoria RAM (evita escrituras basura en disco)
                output_buffer = BytesIO()
                
                # Guardamos la imagen en el buffer aplicando la conversión y compresión neón a WebP
                img.save(output_buffer, format='WEBP', quality=80)
                output_buffer.seek(0)
                
                # Reasignamos el archivo modificado al campo del modelo
                nuevo_nombre = f"{os.path.splitext(self.imagen.name)[0]}.webp"
                self.imagen = ContentFile(output_buffer.read(), name=nuevo_nombre)
                
            except Exception as e:
                # Si por alguna razón falla Pillow, dejamos pasar la imagen original para no romper el SaaS
                pass

        super().save(*args, **kwargs)





class CodigoDescuento(ScopedModel):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='codigos_descuento')
    nombre_codigo = models.CharField(max_length=50)
    fecha_caducidad = models.DateTimeField()
    limite_usos = models.PositiveIntegerField(default=100)
    usos_actuales = models.PositiveIntegerField(default=0)
    precio_especial = models.DecimalField(max_digits=10, decimal_places=2)
    precio_especial_dia = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Descuento (Por 1 Día)")
    
    # 🚀 NUEVO: Control de borrado lógico (Soft Delete)
    activo = models.BooleanField(default=True, verbose_name="¿Código Activo?")

    # 🚀 NUEVO SENIOR: Relación con el Pase Específico (Cupón Granular)
    pase_aplicable = models.ForeignKey(
        'TipoPase', # Usamos string porque el modelo TipoPase se define más abajo
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='cupones_asociados',
        help_text="Si se deja en blanco, el cupón aplica para todo el evento. Si se selecciona un pase, solo servirá para ese pase."
    )

    class Meta:
        unique_together = ('evento', 'nombre_codigo')

    def __str__(self):
        return f"{self.nombre_codigo} - Evento: {self.evento.nombre}"

    @property
    def es_valido(self):
        from django.utils import timezone
        # 🛡️ FIX SENIOR: Ahora valida fechas, cupos Y que un admin no lo haya desactivado manualmente
        return self.activo and timezone.now() <= self.fecha_caducidad and self.usos_actuales < self.limite_usos


class TipoPase(ScopedModel):
    """
    Modelo Avanzado: Permite a las academias crear múltiples opciones de compra 
    para un mismo evento (Ej: Solo Social, Full Pass, Taller Especial).
    """
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='pases_personalizados')
    nombre = models.CharField(max_length=100) # Ej: "Solo Social - Viernes"
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    
    # 🧠 CLAVE PARA LOS QRs: Le decimos al sistema cuántas veces puede entrar con este pase
    accesos_permitidos = models.PositiveIntegerField(
        default=1, 
        help_text="¿Cuántos días/veces puede escanear su QR con este pase?"
    )

    # 🚀 NUEVO SENIOR: Factor multiplicador para automatizar parejas o grupos
    qrs_por_pase = models.PositiveIntegerField(
        default=1, 
        verbose_name="Personas por Pase",
        help_text="1 = Individual, 2 = Pareja. Define cuántos QRs se generan al comprar 1 unidad."
    )

    # 🚀 FIX SENIOR: Control para mostrar u ocultar pases al público
    activo = models.BooleanField(default=True, verbose_name="¿Pase Activo?")
    admissions_per_unit = models.PositiveIntegerField(null=True, blank=True,
        help_text='Unidades comerciales por pase. Vacío conserva acceso legacy sin generar cargos SaaS.')

    class Meta:
        ordering = ['precio'] # Ordena del más barato al más caro en el select

    def __str__(self):
        return f"{self.nombre} - ${self.precio} ({self.evento.nombre})"
    
class FasePreventa(ScopedModel):
    """
    Define los bloques de tiempo (Tiers) para las ventas.
    Ej: "Preventa 1" (hasta el 15 de Julio), "Preventa 2" (hasta el 1 de Agosto).
    """
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='fases_preventa')
    nombre_fase = models.CharField(max_length=50) # Ej: "Lote 1", "Early Bird"
    fecha_limite = models.DateTimeField(help_text="Hasta cuándo estará activa esta fase")
    
    # 🛡️ MODO CLÁSICO: Precios que se usan SÓLO si el evento NO tiene "Pases a la carta"
    precio_full = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    precio_dia = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['fecha_limite'] # Orden cronológico automático

    def __str__(self):
        return f"{self.nombre_fase} - Vence: {self.fecha_limite.strftime('%d/%m/%Y')} ({self.evento.nombre})"


class PrecioFasePase(ScopedModel):
    """
    MATRIZ DE PRECIOS (Tabla Pivote): 
    Define exactamente cuánto cuesta un "Tipo de Pase" específico dentro de una "Fase" específica.
    """
    fase = models.ForeignKey(FasePreventa, on_delete=models.CASCADE, related_name='precios_pases')
    pase = models.ForeignKey(TipoPase, on_delete=models.CASCADE, related_name='precios_fases')
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        # 🔒 Seguridad: Un mismo pase no puede tener dos precios distintos en la misma fase
        unique_together = ('fase', 'pase') 

    def __str__(self):
        return f"{self.pase.nombre} en {self.fase.nombre_fase}: ${self.precio}"

class ReciboEvento(ScopedModel):
    class PaymentStatus(models.TextChoices):
        LEGACY = 'LEGACY', 'Histórico (verificación no certificada)'
        PENDING = 'PENDING', 'Pendiente de aprobación'
        CONFIRMED = 'CONFIRMED', 'Pago confirmado'
        CANCELLED = 'CANCELLED', 'Anulado (no implica devolución)'
        REFUNDED = 'REFUNDED', 'Devolución registrada'
        REVIEW = 'REVIEW', 'En revisión'

    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    registration_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    price_snapshot = models.JSONField(default=dict, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    MEDIOS_PAGO = (
        ('EFECTIVO', 'Efectivo'),
        ('TRANSFERENCIA', 'Transferencia / Nequi'),
        ('TARJETA', 'Tarjeta de Crédito/Débito'),
    )
    ORIGEN_REGISTRO = (
        ('ONLINE', 'Inscripción Web'),
        ('PUERTA', 'Vendido en Taquilla / Puerta'),
    )
    
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='recibos_evento')
    numero_recibo = models.CharField(max_length=50, unique=True)
    
    comprador_nombre = models.CharField(max_length=150)
    comprador_correo = models.EmailField(blank=True, null=True)
    comprador_telefono = models.CharField(max_length=30)
    
    cantidad_entradas = models.PositiveIntegerField(default=1)
    codigo_descuento_usado = models.ForeignKey(CodigoDescuento, on_delete=models.SET_NULL, null=True, blank=True)
    
    precio_unitario_aplicado = models.DecimalField(max_digits=10, decimal_places=2)
    monto_total = models.DecimalField(max_digits=10, decimal_places=2)
    
    medio_pago = models.CharField(max_length=20, choices=MEDIOS_PAGO, default='TRANSFERENCIA')
    origen = models.CharField(max_length=10, choices=ORIGEN_REGISTRO, default='ONLINE')
    
    # Si compras en puerta, no es obligatorio subir imagen
    comprobante_pago = models.ImageField(storage=private_storage, validators=[validate_private_upload], upload_to='comprobantes_eventos/', blank=True, null=True)
    revisado_por_admin = models.BooleanField(default=False)
    
    # Campo booleano para taquilla: registra si la persona que compró en puerta ya pasó directo al salón
    ingresado_puerta = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)
    # 🚀 NUEVO: Conectamos la venta con el Pase y la Fase exacta
    tipo_pase = models.ForeignKey(TipoPase, on_delete=models.SET_NULL, null=True, blank=True, related_name='recibos')
    fase_preventa = models.ForeignKey(FasePreventa, on_delete=models.SET_NULL, null=True, blank=True, related_name='recibos')

    anulado = models.BooleanField(default=False, verbose_name="¿Recibo Anulado?")

    def save(self, *args, **kwargs):
        if not self.numero_recibo:
            # A stable random reference avoids count()+1 races on every database.
            self.numero_recibo = f"RE-A{self.evento.academia_id}-E{self.evento_id}-{uuid.uuid4().hex[:16]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_recibo} - {self.comprador_nombre} ({self.evento.nombre})"


class EntradaQR(ScopedModel):
    """Genera boletas individuales con control de múltiples asistencias (días)."""
    recibo = models.ForeignKey(ReciboEvento, on_delete=models.CASCADE, related_name='boletas_qr')
    codigo_unico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    admission = models.OneToOneField('Admission', null=True, blank=True, on_delete=models.PROTECT, related_name='credential')
    revoked_at = models.DateTimeField(null=True, blank=True)
    
    # 🔄 CAMBIO: De booleano a contador de asistencias permitidas
    # Si es evento de 1 día, tendrá 1. Si es de 3 días, tendrá 3.
    asistencias_permitidas = models.PositiveIntegerField(default=1)
    asistencias_consumidas = models.PositiveIntegerField(default=0)
    
    # Mantenemos registro de la última entrada
    fecha_ultimo_ingreso = models.DateTimeField(null=True, blank=True)
    
    imagen_qr = models.ImageField(storage=private_storage, validators=[validate_private_upload], upload_to='qrs_eventos/', blank=True, null=True)

    @property
    def ingresado(self):
        """Mantiene compatibilidad: retorna True si ya no puede entrar más."""
        return self.asistencias_consumidas >= self.asistencias_permitidas

    def __str__(self):
        return f"Boleta {self.codigo_unico} ({self.asistencias_consumidas}/{self.asistencias_permitidas} días)"


class GastoEvento(ScopedModel):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='gastos_evento')
    concepto = models.CharField(max_length=200)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Gasto: {self.concepto} - ${self.monto:,.0f}"
    


    

class ColaboradorEvento(ScopedModel):
    """
    Controla el acceso VIP de usuarios de otras academias a eventos específicos.
    """
    ROLES = (
        ('METRICAS', 'Gestor de Métricas y Taquilla'),
        ('TAQUILLA', 'Solo Escáner QR y Taquilla'),
    )
    
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='colaboradores')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='eventos_colaborados')
    rol = models.CharField(max_length=20, choices=ROLES, default='METRICAS')
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Un usuario no puede ser agregado dos veces al mismo evento
        unique_together = ('evento', 'usuario')

    def __str__(self):
        return f"{self.usuario.email} - {self.evento.nombre} ({self.get_rol_display()})"


class Admission(ScopedModel):
    """A stable access entitlement, independent of its replaceable QR and scans."""
    receipt = models.ForeignKey(ReciboEvento, on_delete=models.PROTECT, related_name='admissions')
    ordinal = models.PositiveIntegerField()
    commercial_unit = models.BooleanField(default=False)
    access_limit = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['receipt', 'ordinal'], name='admission_receipt_ordinal')]


class CheckIn(ScopedModel):
    credential = models.ForeignKey(EntradaQR, on_delete=models.PROTECT, related_name='checkins')
    credential_code = models.UUIDField()
    occurred_at = models.DateTimeField(default=timezone.now)
    day = models.DateField()
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    result = models.CharField(max_length=24)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['credential', 'day'], condition=models.Q(result='SUCCESS'),
                                               name='checkin_once_per_day')]


class EventRefund(ScopedModel):
    receipt = models.ForeignKey(ReciboEvento, on_delete=models.PROTECT, related_name='refund_records')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, unique=True)
    reason = models.CharField(max_length=255)
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
