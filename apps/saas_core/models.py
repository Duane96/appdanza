from django.db import models
from apps.academias.models import Academia # Importamos tu modelo actual de Academia
from django.utils import timezone


class PlanSaaS(models.Model):
    TIPO_COBRO_CHOICES = [
        ('MENSUAL', 'Suscripción Mensual / Días Fijos'),
        ('POR_EVENTO', 'Plan Transaccional Pure Event (Mensualidad $0)'),
    ]
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Plan")
    tipo_cobro = models.CharField(max_length=15, choices=TIPO_COBRO_CHOICES, default='MENSUAL')
    precio_mensual = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio Mensual (COP)")
    max_estudiantes = models.IntegerField(default=50, verbose_name="Límite de Estudiantes")
    
    permite_multimedia = models.BooleanField(default=False, verbose_name="Acceso a Módulo Multimedia")
    permite_finanzas = models.BooleanField(default=True, verbose_name="Acceso a Módulo Finanzas/DIAN")
    permite_asistencias_qr = models.BooleanField(default=True, verbose_name="Acceso a Escáner QR")
    permite_eventos = models.BooleanField(default=False, verbose_name="Acceso a Módulo Eventos")
    permite_estudiantes = models.BooleanField(default=True, verbose_name="Acceso a Módulo Estudiantes")
    permite_tienda = models.BooleanField(default=False, verbose_name="Acceso a Módulo Tienda/POS")
    permite_profesores = models.BooleanField(default=False, verbose_name="Acceso a Módulo Profesores/Nómina")
    permite_calendario = models.BooleanField(default=False, verbose_name="Acceso a Módulo Calendario")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_cobro_display()})"


class SuscripcionAcademia(models.Model):
    """Vincula una academia con un plan SaaS y controla su estado de activación."""
    ESTADOS = (
        ('ACTIVO', 'Activo / Al Día'),
        ('MORA', 'En Mora (Período de Gracia)'),
        ('SUSPENDIDO', 'Suspendido por Falta de Pago'),
        ('PRUEBA', 'Período de Prueba'),
    )
    
    academia = models.OneToOneField(Academia, on_delete=models.CASCADE, related_name='suscripcion_saas')
    # 2. 🚀 MAGIA: null=True, blank=True para que en PRUEBA no exija plan comercial
    plan = models.ForeignKey(PlanSaaS, on_delete=models.SET_NULL, null=True, blank=True, related_name='academias_inscritas')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='SUSPENDIDO')
    
    # Forzado manual para activar/desactivar módulos sin importar el plan (Tu súper poder)
    bloqueo_manual_multimedia = models.BooleanField(default=False, verbose_name="Bloquear Multimedia Manualmente")
    bloqueo_manual_finanzas = models.BooleanField(default=False, verbose_name="Bloquear Finanzas Manualmente")
    bloqueo_manual_asistencias = models.BooleanField(default=False, verbose_name="Bloquear Asistencias Manualmente")
    bloqueo_manual_eventos = models.BooleanField(default=False, verbose_name="Bloquear Eventos Manualmente")
    bloqueo_manual_estudiantes = models.BooleanField(default=False, verbose_name="Bloquear Estudiantes Manualmente")
    bloqueo_manual_tienda = models.BooleanField(default=False, verbose_name="Bloquear Tienda Manualmente")
    bloqueo_manual_profesores = models.BooleanField(default=False, verbose_name="Bloquear Profesores Manualmente")
    bloqueo_manual_calendario = models.BooleanField(default=False, verbose_name="Bloquear Calendario Manualmente")

    # Evita que apliquen al plan gratis más de una vez en la vida de la academia
    ya_uso_prueba_gratis = models.BooleanField(
        default=False, 
        verbose_name="¿Ya consumió su beneficio de prueba gratis?"
    )

    # ⏱️ DURACIÓN CONFIGURABLE DEL PERÍODO GRATUITO
    # Permite que definas dinámicamente cuántos días le regalas a este inquilino
    dias_regalados_prueba = models.IntegerField(
        default=15, 
        verbose_name="Días autorizados para el Plan Gratis"
    )
    
    fecha_inicio = models.DateField()
    fecha_vencimiento = models.DateField()

    # 🌟 LA JUGADA DE SOCIOS: Interruptor maestro para omitir cobros
    es_cuenta_partner_gratis = models.BooleanField(
        default=False, 
        verbose_name="Cuenta Aliada / Gratis Permanente (No cobra plan ni comisiones)"
    )

    comision_por_tiquete = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0, 
        verbose_name="Comisión por Ticket (Eventos)"
    )

    def __span__(self):
        return f"{self.academia.nombre} - {self.plan.nombre} ({self.estado})"
    
    @property
    def modulo_eventos_activo(self):
        """
        Prioridad:
        1. Bloqueo manual (Override maestro): Si está bloqueado, nadie entra.
        2. Estado Partner: Si es Partner, acceso total.
        3. Plan: Si no es Partner, solo acceso si el plan lo permite.
        """
        if self.bloqueo_manual_eventos: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_eventos

    # 🚀 ACTUALIZA LA PROPERTY DE EVENTOS PARA QUE NO DEPENDA DEL PLAN:
    @property
    def modulo_eventos_activo(self):
        """
        NUEVA LÓGICA: Los eventos son un módulo 100% independiente de los planes.
        Depende exclusivamente del interruptor manual o de si es Partner VIP.
        (Nota: bloqueo_manual_eventos=False significa que SÍ lo tiene activo)
        """
        if self.es_cuenta_partner_gratis: return True
        return not self.bloqueo_manual_eventos

    @property
    def modulo_calendario_activo(self):
        """Lógica de activación para Calendario"""
        if self.bloqueo_manual_calendario: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_calendario
    
    @property
    def modulo_multimedia_activo(self):
        if self.bloqueo_manual_multimedia: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_multimedia

    @property
    def modulo_finanzas_activo(self):
        if self.bloqueo_manual_finanzas: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_finanzas

    @property
    def modulo_asistencias_activo(self):
        if self.bloqueo_manual_asistencias: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_asistencias_qr
    
    @property
    def modulo_estudiantes_activo(self):
        if self.bloqueo_manual_estudiantes: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_estudiantes
    
    @property
    def modulo_tienda_activo(self):
        if self.bloqueo_manual_tienda: return False
        if self.es_cuenta_partner_gratis: return True
        return self.plan.permite_tienda
    
    @property
    def dias_restantes_licencia(self):
        """Calcula de forma exacta cuántos días le quedan de uso a la academia en Hora Colombia."""
        # Forzamos la zona horaria local colombiana configurada en Django (America/Bogota)
        hoy_colombia = timezone.localtime(timezone.now()).date()
        delta = self.fecha_vencimiento - hoy_colombia
        return delta.days

    @property
    def mostrar_alerta_vencimiento(self):
        """Condición: Muestra alerta permanente durante los 5 días previos al vencimiento."""
        if self.es_cuenta_partner_gratis or self.estado == 'SUSPENDIDO':
            return False
        
        dias = self.dias_restantes_licencia
        # Retorna True si está entre el día 0 (último día de pago) y el día 5 de anticipación
        return 0 <= dias <= 5

    @property
    def esta_bloqueada(self):
        """
        Bloqueo inteligente:
        - Si es partner, nunca se bloquea.
        - Si lo pasas a SUSPENDIDO manualmente, se bloquea.
        - Si tiene más de 5 días de vencido (Mora vencida), se bloquea automáticamente.
        """
        if self.es_cuenta_partner_gratis:
            return False
            
        if self.estado == 'SUSPENDIDO':
            return True
            
        # Si ya pasaron los 5 días de gracia (días restantes es menor a -5)
        if self.dias_restantes_licencia < -5:
            return True
            
        return False

    @property
    def esta_en_mora(self):
        """
        Detecta si la academia está en los 5 días de gracia.
        Retorna True si los días restantes están entre -1 y -5.
        """
        if self.es_cuenta_partner_gratis or self.estado in ['PRUEBA', 'SUSPENDIDO']:
            return False
            
        # Si está entre el día de vencimiento (0) y el día de corte final (-5)
        if -5 <= self.dias_restantes_licencia < 0:
            return True
            
        if self.estado == 'MORA':
            return True
            
        return False
    



class LandingPageConfig(models.Model):
    titulo_principal = models.CharField(max_length=200)
    subtitulo_principal = models.TextField()

    boton_principal_texto = models.CharField(max_length=100)
    boton_principal_url = models.CharField(max_length=300)

    whatsapp = models.CharField(max_length=30, blank=True)
    email_contacto = models.EmailField(blank=True)

    mostrar_capturas = models.BooleanField(default=True)
    mostrar_faq = models.BooleanField(default=True)

    activo = models.BooleanField(default=True)

    def __str__(self):
        return "Configuración Landing"
    

class ScreenshotLanding(models.Model):
    titulo = models.CharField(max_length=100)

    imagen = models.ImageField(
        upload_to='landing/screenshots/'
    )

    descripcion = models.TextField(blank=True)

    orden = models.PositiveIntegerField(default=0)

    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden']


class TestimonioLanding(models.Model):
    nombre = models.CharField(max_length=100)

    academia = models.CharField(max_length=150)

    foto = models.ImageField(
        upload_to='landing/testimonios/',
        blank=True,
        null=True
    )

    comentario = models.TextField()

    activo = models.BooleanField(default=True)



class FAQLanding(models.Model):
    pregunta = models.CharField(max_length=300)

    respuesta = models.TextField()

    orden = models.PositiveIntegerField(default=0)

    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden']


class BeneficioLanding(models.Model):
    icono = models.CharField(
        max_length=50,
        help_text="Bootstrap Icon"
    )

    titulo = models.CharField(max_length=100)

    descripcion = models.TextField()

    orden = models.PositiveIntegerField(default=0)

    activo = models.BooleanField(default=True)


class VideoLanding(models.Model):
    titulo = models.CharField(max_length=100)

    youtube_url = models.URLField()

    activo = models.BooleanField(default=True)


class ConfigPagoGlobalSaaS(models.Model):
    """Guarda el método de recaudo oficial del SaaS (Banco, Nequi, Llave, etc.)."""
    
    METODO_CHOICES = [
        ('BANCO', 'Cuenta Bancaria Tradicional'),
        ('NEQUI', 'Plataforma Nequi (Número de celular)'),
        ('DAVIPLATA', 'Plataforma Daviplata (Número de celular)'),
        ('LLAVE', 'Llave Transfiya / Celular / Correo'),
        ('QR_DIRECTO', 'Código QR de Transferencia Directa'),
    ]
    
    tipo_metodo = models.CharField(
        max_length=20, 
        choices=METODO_CHOICES, 
        default='NEQUI',
        verbose_name="Tipo de Canal de Pago"
    )
    
    nombre_proveedor = models.CharField(
        max_length=100, 
        verbose_name="Entidad / Proveedor",
        help_text="Ej: Bancolombia, Nequi, Davivienda, etc."
    )
    
    identificador_pago = models.CharField(
        max_length=150, 
        verbose_name="Número de Cuenta / Celular / Llave",
        help_text="El dato exacto que el cliente debe copiar para transferir."
    )
    
    # 🔓 Flexibilidad Total: Campos opcionales para no romper flujos si usas Nequi o llaves
    titular = models.CharField(
        max_length=150, 
        blank=True, 
        null=True, 
        verbose_name="Titular de la cuenta (Opcional)"
    )
    
    documento_titular = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        verbose_name="Cédula/NIT del Titular (Opcional)"
    )
    
    instrucciones_adicionales = models.TextField(
        blank=True, 
        help_text="Mensaje instructivo (Ej: 'Una vez transferido, envía el pantallazo al WhatsApp 310...')"
    )

    class Meta:
        verbose_name = "Configuración de Pago Global SaaS"
        verbose_name_plural = "Configuraciones de Pago Global SaaS"

    def __str__(self):
        return f"Recaudo vía {self.get_tipo_metodo_display()} ({self.nombre_proveedor})"
    
class ReportePagoSaaS(models.Model):
    """Modelo para almacenar los comprobantes de pago subidos por las academias."""
    
    ESTADOS = [
        ('PENDIENTE', 'Pendiente de Revisión'),
        ('APROBADO', 'Aprobado y Renovado'),
        ('RECHAZADO', 'Rechazado'),
    ]

    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='reportes_pago')
    plan = models.ForeignKey(PlanSaaS, on_delete=models.SET_NULL, null=True)
    comprobante = models.FileField(upload_to='saas_comprobantes/%Y/%m/')
    fecha_envio = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')

    class Meta:
        ordering = ['-fecha_envio']
        verbose_name = 'Reporte de Pago SaaS'
        verbose_name_plural = 'Reportes de Pago SaaS'

    def __str__(self):
        return f"Pago de {self.academia.nombre} - {self.get_estado_display()}"
    

class ReciboSaaS(models.Model):
    """Contabilidad Global del Dueño de la Plataforma (Registro de tus ingresos)"""
    numero_recibo = models.CharField(max_length=20, unique=True, editable=False)
    academia = models.ForeignKey(Academia, on_delete=models.PROTECT, related_name='recibos_pagados_saas')
    plan = models.ForeignKey(PlanSaaS, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    medio_pago = models.CharField(max_length=50, default='TRANSFERENCIA/COMPROBANTE')
    concepto = models.CharField(max_length=255)
    

    class Meta:
        ordering = ['-fecha']
        verbose_name = "Recibo de Ingreso SaaS"
        verbose_name_plural = "Recibos de Ingreso SaaS"

    def __str__(self):
        return f"{self.numero_recibo} - {self.academia.nombre} - ${self.monto}"

    def save(self, *args, **kwargs):
        """Autogenera un consecutivo único para tus facturas SaaS"""
        if not self.numero_recibo:
            ultimo = ReciboSaaS.objects.order_by('id').last()
            consecutivo = (ultimo.id + 1) if ultimo else 1
            # Tus recibos tendrán el prefijo SAAS-0001, SAAS-0002...
            self.numero_recibo = f"SAAS-{consecutivo:04d}"
        super().save(*args, **kwargs)


class GastoSaaS(models.Model):
    """Registro de gastos operativos del dueño de la plataforma (Servidores, dominios, etc.)"""
    fecha = models.DateField(default=timezone.now, verbose_name="Fecha del Gasto")
    monto = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    concepto = models.CharField(max_length=255, verbose_name="Descripción / Concepto")
    comprobante = models.FileField(upload_to='saas/gastos_comprobantes/', blank=True, null=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = "Gasto SaaS"
        verbose_name_plural = "Gastos SaaS"

    def __str__(self):
        return f"{self.fecha} - {self.concepto} - ${self.monto}"