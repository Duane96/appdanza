from django.contrib import admin
from .models import VideoClase, ModuloClase

@admin.register(VideoClase)
class VideoClaseAdmin(admin.ModelAdmin):
    # Columnas que se mostrarán en la lista del admin
    list_display = ('titulo', 'get_modulo_titulo', 'get_academia', 'youtube_id', 'fecha_subida')
    # Filtros laterales, permitimos filtrar por el módulo (que ya vendrá filtrado por academia)
    list_filter = ('modulo__titulo', 'modulo__academia')
    # Buscador por título de video o ID de YouTube
    search_fields = ('titulo', 'youtube_id')
    # Orden predeterminado: los más nuevos primero
    ordering = ('-fecha_subida',)

    def get_queryset(self, request):
        """
        FILTRO MULTI-TENANT CRÍTICO:
        Filtra los videos para que el administrador de una academia solo vea 
        los videos que pertenecen a los módulos de SU academia.
        """
        qs = super().get_queryset(request)
        
        # Si es el superusuario global de la plataforma (Panel Maestro), ve todo.
        if request.user.is_superuser and getattr(request.user, 'is_staff', False) and not getattr(request.user, 'academia_id', None):
            return qs
            
        # Obtenemos la academia del usuario autenticado (ajusta 'request.user.academia' según tu arquitectura)
        academia_usuario = getattr(request.user, 'academia', None)
        if academia_usuario:
            return qs.filter(modulo__academia=academia_usuario)
            
        return qs.none() # Si no tiene academia asociada por seguridad no ve nada

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        FILTRO EN FORMULARIOS:
        Cuando el admin esté creando o editando un VideoClase, el desplegable (Select)
        de 'modulo' SOLO mostrará los módulos que pertenecen a su propia academia.
        """
        if db_field.name == "modulo":
            academia_usuario = getattr(request.user, 'academia', None)
            if academia_usuario and not request.user.is_superuser:
                # Limitamos las opciones del FK a los módulos de la academia del usuario
                kwargs["queryset"] = ModuloClase.objects.filter(academia=academia_usuario)
            elif not request.user.is_superuser:
                kwargs["queryset"] = ModuloClase.objects.none()
                
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # --- MÉTODOS PARA MOSTRAR COLUMNAS PERSONALIZADAS ---

    @admin.display(description='Módulo')
    def get_modulo_titulo(self, obj):
        """Retorna el título del módulo asignado."""
        return obj.modulo.titulo

    @admin.display(description='Academia / Escuela')
    def get_academia(self, obj):
        """Retorna el nombre de la academia a la que pertenece el módulo/video."""
        return obj.modulo.academia.nombre # Ajusta '.nombre' según tu modelo Academia