# apps/eventos/models.py
import uuid
from django.db import models
from apps.academias.models import Academia
import os


from django.utils.text import slugify
from io import BytesIO  # O simplemente 'from io import BytesIO'
from django.core.files.base import ContentFile
from PIL import Image

from apps.academias.models import TenantModel

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

    class Meta:
        unique_together = ('academia', 'slug')
        ordering = ['-fecha']

    # 🧠 MÉTODO SENIOR: Cómputo de Deudas Dinámicas con Reglas de País
    # 🧠 MÉTODO SENIOR: Cómputo de Deudas Dinámicas con Reglas de País
    def calcular_estado_comisiones(self):
        """Calcula de manera exacta las comisiones transaccionales manejando el salvoconducto Partner."""
        suscripcion = self.academia.suscripcion_saas
        
        # 🐛 EL BUG ESTABA AQUÍ: Usabas .count() (contar recibos). Si 1 recibo tenía 5 entradas, lo contaba como 1.
        # ✅ CORRECCIÓN SENIOR: Usamos models.Sum('cantidad_entradas') para contar a las personas reales.
        
        # Conteo físico real de registros emitidos para el evento actual
        total_online = self.recibos_evento.filter(origen='ONLINE').aggregate(total=models.Sum('cantidad_entradas'))['total'] or 0
        total_puerta = self.recibos_evento.filter(origen='PUERTA').aggregate(total=models.Sum('cantidad_entradas'))['total'] or 0
        
        # 🎁 FILTRO VIP COMPAÑEROS DE PRUEBA: Si es aliado o partner, la plataforma reporta cero deudas
        if suscripcion and suscripcion.es_cuenta_partner_gratis:
            return {
                'total_online': total_online,
                'total_puerta': total_puerta,
                'deuda_online': 0,
                'deuda_puerta': 0,
                'es_minima_online': False,
                'divisa': 'COP',
                'modo_partner': True
            }
            
        # 💵 MATEMÁTICAS COMERCIALES CLIENTES CONVENCIONALES
        # Ahora sí, multiplicamos la cantidad exacta de BOLETAS por la tarifa del SaaS
        deuda_online_calculada = total_online * 5000
        es_minima = False
        
        # Regla de Oro Local: Piso mínimo garantizado de $100.000 COP por evento en Colombia
        if self.academia.pais == 'CO' and deuda_online_calculada > 0 and deuda_online_calculada < 100000:
            deuda_online_calculada = 100000
            es_minima = True
            
        # Regla Internacional: 5% sobre el dinero bruto acumulado online en su divisa nativa
        if self.academia.pais != 'CO':
            total_dinero_online = self.recibos_evento.filter(origen='ONLINE').aggregate(total=models.Sum('monto_total'))['total'] or 0
            deuda_online_calculada = float(total_dinero_online) * 0.05
            
        return {
            'total_online': total_online,
            'total_puerta': total_puerta,
            'deuda_online': deuda_online_calculada,
            'deuda_puerta': 0, 
            'es_minima_online': es_minima,
            'divisa': 'COP' if self.academia.pais == 'CO' else 'USD',
            'modo_partner': False
        }
    
    def __str__(self):
        return f"{self.nombre} ({self.academia.nombre})"
    
    def save(self, *args, **kwargs):
        # 1. Aseguramos el slug antes de guardar
        if not self.slug:
            self.slug = slugify(self.nombre)

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





class CodigoDescuento(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='codigos_descuento')
    nombre_codigo = models.CharField(max_length=50)
    fecha_caducidad = models.DateTimeField()
    limite_usos = models.PositiveIntegerField(default=100)
    usos_actuales = models.PositiveIntegerField(default=0)
    precio_especial = models.DecimalField(max_digits=10, decimal_places=2)
    # NUEVO: Precio aplicado SOLAMENTE si el evento es multidía y el usuario elige Pase por 1 Día
    precio_especial_dia = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Descuento (Por 1 Día)")

    class Meta:
        unique_together = ('evento', 'nombre_codigo')

    def __str__(self):
        return f"{self.nombre_codigo} - Evento: {self.evento.nombre}"

    @property
    def es_valido(self):
        from django.utils import timezone
        return timezone.now() <= self.fecha_caducidad and self.usos_actuales < self.limite_usos


class TipoPase(models.Model):
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

    class Meta:
        ordering = ['precio'] # Ordena del más barato al más caro en el select

    def __str__(self):
        return f"{self.nombre} - ${self.precio} ({self.evento.nombre})"
    
class FasePreventa(models.Model):
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


class PrecioFasePase(models.Model):
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

class ReciboEvento(models.Model):
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
    comprobante_pago = models.ImageField(upload_to='comprobantes_eventos/', blank=True, null=True)
    revisado_por_admin = models.BooleanField(default=True)
    
    # Campo booleano para taquilla: registra si la persona que compró en puerta ya pasó directo al salón
    ingresado_puerta = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)
    # 🚀 NUEVO: Conectamos la venta con el Pase y la Fase exacta
    tipo_pase = models.ForeignKey(TipoPase, on_delete=models.SET_NULL, null=True, blank=True, related_name='recibos')
    fase_preventa = models.ForeignKey(FasePreventa, on_delete=models.SET_NULL, null=True, blank=True, related_name='recibos')

    anulado = models.BooleanField(default=False, verbose_name="¿Recibo Anulado?")

    def save(self, *args, **kwargs):
        # 1. Asignar numeración secuencial robusta orientada a SaaS (Multi-Tenant)
        if not self.numero_recibo:
            # Contamos cuántos recibos existen ya para este evento específico
            count = ReciboEvento.objects.filter(evento=self.evento).count()
            
            # 🚀 CORRECCIÓN SENIOR: Prefijo único por Academia y Evento
            # Estructura: RE-A{id_academia}-E{id_evento}-{consecutivo}
            # Ejemplo de salida: RE-A1-E5-0001
            prefijo = f"RE-A{self.evento.academia.id}-E{self.evento.id}"
            nuevo_numero = f"{prefijo}-{count + 1:04d}"
            
            # Seguridad extra: Buscamos globalmente si por concurrencia ya existe
            while ReciboEvento.objects.filter(numero_recibo=nuevo_numero).exists():
                count += 1
                nuevo_numero = f"{prefijo}-{count + 1:04d}"
            
            self.numero_recibo = nuevo_numero
            
        super().save(*args, **kwargs)

        # 2. DETONANTE INTELIGENTE DE BOLETAS QR
        if self.origen == 'ONLINE' and not self.boletas_qr.exists():
            for _ in range(self.cantidad_entradas):
                EntradaQR.objects.create(recibo=self)


    def __str__(self):
        return f"{self.numero_recibo} - {self.comprador_nombre} ({self.evento.nombre})"


class EntradaQR(models.Model):
    """Genera boletas individuales con control de múltiples asistencias (días)."""
    recibo = models.ForeignKey(ReciboEvento, on_delete=models.CASCADE, related_name='boletas_qr')
    codigo_unico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # 🔄 CAMBIO: De booleano a contador de asistencias permitidas
    # Si es evento de 1 día, tendrá 1. Si es de 3 días, tendrá 3.
    asistencias_permitidas = models.PositiveIntegerField(default=1)
    asistencias_consumidas = models.PositiveIntegerField(default=0)
    
    # Mantenemos registro de la última entrada
    fecha_ultimo_ingreso = models.DateTimeField(null=True, blank=True)
    
    imagen_qr = models.ImageField(upload_to='qrs_eventos/', blank=True, null=True)

    @property
    def ingresado(self):
        """Mantiene compatibilidad: retorna True si ya no puede entrar más."""
        return self.asistencias_consumidas >= self.asistencias_permitidas

    def __str__(self):
        return f"Boleta {self.codigo_unico} ({self.asistencias_consumidas}/{self.asistencias_permitidas} días)"


class GastoEvento(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='gastos_evento')
    concepto = models.CharField(max_length=200)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Gasto: {self.concepto} - ${self.monto:,.0f}"
    


    

