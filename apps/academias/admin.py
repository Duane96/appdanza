# apps/academias/admin.py
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Academia, PerfilUsuario

# Mantenemos los registros que ya tenías
@admin.register(Academia)
class AcademiaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'nit', 'telefono', 'activo', 'fecha_creacion')
    search_fields = ('nombre', 'slug', 'nit')
    list_filter = ('activo', 'fecha_creacion')
    prepopulated_fields = {'slug': ('nombre',)}


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