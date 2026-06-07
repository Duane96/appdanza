# apps/academias/models.py
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from gestoracademia.tenants import get_current_tenant

from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os
from django.db import models

class TenantManager(models.Manager):
    """
    Manager personalizado para aislar QuerySets de manera automática
    según el tenant (academia) activo en la petición.
    """
    def get_queryset(self):
        tenant = get_current_tenant()
        queryset = super().get_queryset()
        
        # Si hay un tenant activo en el hilo actual, filtramos estrictamente por él
        if tenant:
            return queryset.filter(academia=tenant)
        return queryset


class TenantModel(models.Model):
    """
    Clase abstracta de la cual heredarán TODOS los modelos del proyecto
    que requieran aislamiento por academia (Planes, Estudiantes, Finanzas, etc.)
    """
    academia = models.ForeignKey(
        'academias.Academia', 
        on_delete=models.CASCADE, 
        related_name="%(class)ss" # Ejemplo: estudiantes, planes
    )

    # El objects por defecto ahora es nuestro manager seguro
    objects = TenantManager()
    # Permitir búsquedas sin filtro explícito si se requiere en comandos Cron/Admin
    unfiltered_objects = models.Manager()

    class Meta:
        abstract = True

def ruta_branding_academia(instance, filename):
    """Organiza los archivos de marca (.webp) en la carpeta de la academia."""
    base_name, _ = os.path.splitext(filename)
    return os.path.join('logos_academias', instance.slug, 'branding', f"{base_name}.webp")


class Academia(models.Model):
    # --- CATÁLOGO EXTENDIDO DE 20 ÍCONOS TEMÁTICOS AAA ---
    ICONOS_OPCIONES = (
        ('bi-music-note-beamed', '🎵 Notas Musicales / Ritmo'),
        ('bi-music-note', '🎶 Nota Simple / Melodía'),
        ('bi-disc', '💿 Vinilo / DJ / Social Pista'),
        ('bi-fire', '🔥 Fuego / Pasión / Coreografía'),
        ('bi-lightning-charge-fill', '⚡ Rayo / Urbano / Power / Fuerza'),
        ('bi-heart-pulse-fill', '❤️ Corazón / Salud / Fitness / Bienestar'),
        ('bi-activity', '📈 Ondas / Progreso / Disciplina'),
        ('bi-gem', '💎 Diamante / Técnica Pura / Estilo'),
        ('bi-trophy-fill', '🏆 Trofeo / Alta Competencia / Logros'),
        ('bi-award-fill', '🥇 Medalla / Certificación / Profesorado'),
        ('bi-star-fill', '⭐ Estrella / Élite / Factor Diferenciador'),
        ('bi-people-fill', '👥 Comunidad / Parejas / Clases Grupales'),
        ('bi-emoji-smile-fill', '😀 Sonrisa / Ambiente Sano / Diversión'),
        ('bi-geo-alt-fill', '📍 Pin Ubicación / Sedes / Salones'),
        ('bi-clock-fill', '🕒 Reloj / Horarios Flexibles / Puntualidad'),
        ('bi-calendar-heart', '📅 Calendario / Eventos / Workshops / Galas'),
        ('bi-qr-code-scan', '🔍 Escáner QR / Acceso Seguro / Control'),
        ('bi-shield-check', '🛡️ Escudo / Espacio Seguro / Confianza'),
        ('bi-phone-vibrate', '📱 Celular / App Alumno / Control Digital'),
        ('bi-ticket-perforated-fill', '🎫 Ticket / Entrada / Pasarela Online'),
    )

    # 🚨 LA LÍNEA SALVAVIDAS: Middleware Tenant core
    objects = models.Manager() # El manager por defecto que Django estaba pidiendo a gritos
    unfiltered_objects = models.Manager()

    # --- CAMPOS DE IDENTIDAD (🚨 Corregido: 'logo' ahora usa la función de ruta dinámica) ---
    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Academia")
    slug = models.SlugField(max_length=150, unique=True, verbose_name="Sub-URL / Slug")
    logo = models.ImageField(upload_to=ruta_branding_academia, blank=True, null=True, verbose_name="Logo Oficial")
    color_primario = models.CharField(max_length=7, default="#6f42c1", verbose_name="Color Primario (Hex)")
    color_secundario = models.CharField(max_length=7, default="#e83e8c", verbose_name="Color Secundario (Hex)")
    telefono = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono de Contacto")
    nit = models.CharField(max_length=20, blank=True, null=True, verbose_name="NIT / Identificación Fiscal")
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    # --- CARRETE DE IMÁGENES (HERO SLIDER) ---
    hero_titulo = models.CharField(max_length=200, default="Siente la pasión de bailar", verbose_name="Título Principal - Slide 1")
    hero_eslogan = models.CharField(max_length=255, default="Transformamos tu ritmo interno en arte, salud y disciplina.", verbose_name="Subtítulo/Eslogan - Slide 1")
    hero_imagen_1 = models.ImageField(upload_to=ruta_branding_academia, blank=True, null=True, verbose_name="Imagen de Fondo - Slide 1")
    
    hero_titulo_2 = models.CharField(max_length=200, default="Talleres Especiales y Eventos Sociales", verbose_name="Título Principal - Slide 2")
    hero_eslogan_2 = models.CharField(max_length=255, default="Explora nuestra agenda de actividades mensuales abajo.", verbose_name="Subtítulo/Eslogan - Slide 2")
    hero_imagen_2 = models.ImageField(upload_to=ruta_branding_academia, blank=True, null=True, verbose_name="Imagen de Fondo - Slide 2")

    # --- SECCIÓN INFORMACIÓN EXPANDIDA (NOSOTROS) ---
    info_titulo = models.CharField(max_length=150, default="Sobre Nosotros")
    info_descripcion_1 = models.TextField(default="En nuestra academia nos apasiona guiarte en el viaje del movimiento corporal, rompiendo barreras físicas y mentales.")
    info_descripcion_2 = models.TextField(default="Ofrecemos un espacio optimizado de aprendizaje, profesores altamente experimentados y un ecosistema digital integrado.")
    info_imagen = models.ImageField(upload_to=ruta_branding_academia, blank=True, null=True, verbose_name="Imagen de la Sede/Equipo")
    
    # --- CUADROS ADAPTABLES DE CARACTERÍSTICAS ---
    bloque_1_titulo = models.CharField(max_length=50, default="Alta Competencia", verbose_name="Título Cuadro 1")
    bloque_1_icono = models.CharField(max_length=50, choices=ICONOS_OPCIONES, default="bi-trophy-fill", verbose_name="Ícono Cuadro 1")
    
    bloque_2_titulo = models.CharField(max_length=50, default="Salud & Fitness", verbose_name="Título Cuadro 2")
    bloque_2_icono = models.CharField(max_length=50, choices=ICONOS_OPCIONES, default="bi-heart-pulse-fill", verbose_name="Ícono Cuadro 2")

    bloque_3_titulo = models.CharField(max_length=50, default="Instructores de Élite", blank=True, null=True)
    bloque_3_icono = models.CharField(max_length=50, choices=ICONOS_OPCIONES, default="bi-award-fill", blank=True, null=True)
    
    bloque_4_titulo = models.CharField(max_length=50, default="Ecosistema Digital QR", blank=True, null=True)
    bloque_4_icono = models.CharField(max_length=50, choices=ICONOS_OPCIONES, default="bi-qr-code-scan", blank=True, null=True)

    # --- 🚗 NUEVO CAMPO: IMAGEN DE FONDO EXCLUSIVA PARA EL LOGIN (WRAP EFFECT) ---
    login_imagen = models.ImageField(upload_to=ruta_branding_academia, blank=True, null=True, verbose_name="Imagen de Fondo Login")

    # --- FOOTER Y SEDE ---
    direccion_sede = models.CharField(max_length=255, default="Distrito Social Cra 29 #68-18", verbose_name="Dirección Física")
    horario_atencion = models.CharField(max_length=150, default="Lun - Sáb: 4:00 PM - 9:00 PM", verbose_name="Horario Comercial")
    
    # Canales de Redes
    instagram_url = models.URLField(blank=True, null=True, verbose_name="URL Instagram")
    facebook_url = models.URLField(blank=True, null=True, verbose_name="URL Facebook")
    tiktok_url = models.URLField(blank=True, null=True, verbose_name="URL TikTok")
    youtube_url = models.URLField(blank=True, null=True, verbose_name="URL YouTube")
    whatsapp_url = models.URLField(blank=True, null=True, verbose_name="Enlace Directo WhatsApp")


    # 🌍 GEOLOCALIZACIÓN Y DIVISA SAAS
    PAIS_CHOICES = [
        ('CO', 'Colombia 🇨🇴 (COP)'),
        ('US', 'Estados Unidos 🇺🇸 (USD)'),
        ('ES', 'España 🇪🇸 (EUR)'),
        ('MX', 'México 🇲🇽 (MXN)'),
        ('CL', 'Chile 🇨🇱 (CLP)'),
        ('BR', 'Brasil 🇧🇷 (BRL)'),
        ('PE', 'Perú 🇵🇪 (PEN)'),
        ('OT', 'Otro País (Soporte Especial / USD)'),
    ]
    pais = models.CharField(max_length=2, choices=PAIS_CHOICES, default='CO', verbose_name="País de Operación")
    divisa = models.CharField(max_length=3, default='COP', verbose_name="Divisa de Operación")

    # 🔑 PASARELA DE RECAUDO PROPIA DE LA ACADEMIA (Módulo de Configuración)
    # Colombia -> PayU (Usa Merchant ID, API Key, Account ID)
    payu_merchant_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="PayU Merchant ID")
    payu_api_key = models.CharField(max_length=100, blank=True, null=True, verbose_name="PayU API Key")
    payu_account_id = models.CharField(max_length=50, blank=True, null=True, verbose_name="PayU Account ID")
    
    # Internacional o Cuentas Atlas -> Stripe (Usa llaves estándar)
    stripe_public_key = models.CharField(max_length=150, blank=True, null=True, verbose_name="Stripe Public Key")
    stripe_secret_key = models.CharField(max_length=150, blank=True, null=True, verbose_name="Stripe Secret Key")
    forzar_stripe_fuera_de_radar = models.BooleanField(default=False, verbose_name="Forzar Stripe (Cuenta Internacional/Atlas)")

    # 💳 MÉTODO DE PAGO DE RESPALDO (Garantía para pagarle a Tempo Hub)
    tarjeta_respaldo_configurada = models.BooleanField(default=False, verbose_name="¿Tiene Tarjeta de Respaldo Habilitada?")

    # 🎫 MODO PRODUCTORA / SÓLO EVENTOS
    es_solo_eventos = models.BooleanField(
        default=False, 
        verbose_name="Modo Productora de Eventos",
        help_text="Activa esto si la organización no da clases regulares y solo usa el sistema para vender tickets de eventos/festivales."
    )

    template_landing_personalizado = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text="Ej: academias/landings/duane_aleja.html. Si se deja vacío, usará el index estándar."
    )

    razon_social = models.CharField(max_length=200, blank=True, null=True, verbose_name="Razón Social (Legal)")
    representante_legal = models.CharField(max_length=150, blank=True, null=True, verbose_name="Representante Legal")
    tipo_regimen = models.CharField(
        max_length=100, 
        default="No responsable de IVA", 
        verbose_name="Régimen Fiscal (Ej: Régimen Simple, Responsable de IVA)",
        blank=True, 
        null=True,
    )
    resolucion_facturacion = models.TextField(
        blank=True, 
        null=True, 
        help_text="Texto legal corto que aparecerá en el pie del PDF de la cuenta de cobro."
    )

    # (Mantén tus métodos save() y lógicas WebP idénticas a como me las pasaste)
    def save(self, *args, **kwargs):
        # Auto-asignación de divisas según el mapeo antes de procesar WebP
        mapeo_divisas = {'CO': 'COP', 'US': 'USD', 'ES': 'EUR', 'MX': 'MXN', 'CL': 'CLP', 'BR': 'BRL', 'PE': 'PEN', 'OT': 'USD'}
        self.divisa = mapeo_divisas.get(self.pais, 'USD')

    def __str__(self):
        return self.nombre

    # apps/academias/models.py (Dentro de la clase Academia)

    def save(self, *args, **kwargs):
        mapeo_divisas = {
            'CO': 'COP',
            'US': 'USD',
            'ES': 'EUR',
            'MX': 'MXN',
            'CL': 'CLP',
            'BR': 'BRL',
            'PE': 'PEN',
            'OT': 'USD'
        }

        self.divisa = mapeo_divisas.get(self.pais, 'USD')

        campos_imagen = [
            'hero_imagen_1',
            'hero_imagen_2',
            'logo',
            'info_imagen',
            'login_imagen'
        ]

        for campo in campos_imagen:
            archivo_imagen = getattr(self, campo)

            if archivo_imagen and not archivo_imagen.name.endswith('.webp'):
                try:
                    ...
                except Exception as e:
                    print(f"Error procesando imagen en {campo}: {e}")

        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre

class PerfilUsuario(models.Model):
    """Extiende el modelo User de Django para manejar roles y pertenencia de empleados."""
    ROLES = (
        ('ADMIN_ACADEMIA', 'Administrador de Academia'),
        ('PROFESOR', 'Profesor / Instructor'),
        ('ESTUDIANTE', 'Estudiante (Acceso limitado)'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    # Nota: Un usuario de staff global o dueño del SaaS podría tener academia=None
    academia = models.ForeignKey(Academia, on_delete=models.SET_NULL, null=True, blank=True, related_name="usuarios")
    rol = models.CharField(max_length=20, choices=ROLES, default='ESTUDIANTE')

    def __str__(self):
        return f"{self.user.username} - {self.get_rol_display()} ({self.academia.nombre if self.academia else 'SaaS Global'})"