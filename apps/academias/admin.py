# apps/academias/admin.py
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Academia, PerfilUsuario

@admin.register(Academia)
class AcademiaAdmin(admin.ModelAdmin):
    # 🚀 Ajustamos las columnas para ver info más relevante (incluimos ciudad y modo productora)
    list_display = ('nombre', 'ciudad', 'slug', 'es_solo_eventos', 'activo', 'fecha_creacion')
    search_fields = ('nombre', 'slug', 'nit', 'ciudad')
    list_filter = ('activo', 'es_solo_eventos', 'pais', 'ciudad', 'fecha_creacion')
    prepopulated_fields = {'slug': ('nombre',)}
    
    # 🚀 ORGANIZACIÓN SENIOR: Agrupamos los campos en secciones para no saturar la vista
    fieldsets = (
        ('Información Principal (SaaS)', {
            'fields': (
                'nombre', 'slug', 'activo', 'es_solo_eventos', 
                'template_landing_personalizado' # ¡Aquí está tu campo visible!
            )
        }),
        ('Geolocalización y Moneda', {
            'fields': ('pais', 'ciudad', 'divisa')
        }),
        ('Identidad y Branding', {
            'fields': ('logo', 'color_primario', 'color_secundario', 'login_imagen'),
            'classes': ('collapse',) # Esto hace que la sección inicie cerrada para ahorrar espacio
        }),
        ('Información Fiscal y Legal (DIAN)', {
            'fields': ('razon_social', 'nit', 'representante_legal', 'tipo_regimen', 'resolucion_facturacion'),
            'classes': ('collapse',)
        }),
        ('Configuración de Pasarela (Pagos)', {
            'fields': (
                'tarjeta_respaldo_configurada',
                'payu_merchant_id', 'payu_api_key', 'payu_account_id',
                'stripe_public_key', 'stripe_secret_key', 'forzar_stripe_fuera_de_radar'
            ),
            'classes': ('collapse',)
        }),
        ('Contacto y Redes Sociales', {
            'fields': (
                'telefono', 'direccion_sede', 'horario_atencion', 
                'instagram_url', 'facebook_url', 'tiktok_url', 'youtube_url', 'whatsapp_url'
            ),
            'classes': ('collapse',)
        }),
        ('Personalización de Landing (Hero Slider)', {
            'fields': (
                'hero_titulo', 'hero_eslogan', 'hero_imagen_1',
                'hero_titulo_2', 'hero_eslogan_2', 'hero_imagen_2'
            ),
            'classes': ('collapse',)
        }),
        ('Personalización de Landing (Nosotros y Features)', {
            'fields': (
                'info_titulo', 'info_descripcion_1', 'info_descripcion_2', 'info_imagen',
                'bloque_1_titulo', 'bloque_1_icono',
                'bloque_2_titulo', 'bloque_2_icono',
                'bloque_3_titulo', 'bloque_3_icono',
                'bloque_4_titulo', 'bloque_4_icono'
            ),
            'classes': ('collapse',)
        }),
    )

# 🚀 LA MAGIA: Creamos el Inline para el perfil
class PerfilUsuarioInline(admin.StackedInline):
    model = PerfilUsuario
    can_delete = False
    verbose_name_plural = 'Información de Rol y Academia (SaaS)'
    fk_name = 'user'

# Sobrescribimos el Admin de Usuarios nativo de Django
class UserAdmin(BaseUserAdmin):
    inlines = (PerfilUsuarioInline, )
    
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super(UserAdmin, self).get_inline_instances(request, obj)

# Desregistramos el User nativo y registramos el nuestro mejorado
admin.site.unregister(User)
admin.site.register(User, UserAdmin)