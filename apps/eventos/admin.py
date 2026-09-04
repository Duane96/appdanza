# apps/eventos/admin.py
from django.contrib import admin
from .models import Evento, ColaboradorEvento

# 🚀 1. Registramos Evento PRIMERO y definimos dónde debe buscar
@admin.register(Evento)
class EventoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'academia', 'fecha', 'estado')
    
    # ESTA ES LA LÍNEA MÁGICA QUE SOLUCIONA TU ERROR:
    # Le dice a Django qué columnas buscar cuando uses el autocomplete
    search_fields = ('nombre', 'academia__nombre', 'ciudad') 
    
    list_filter = ('estado', 'es_multidias')
    prepopulated_fields = {'slug': ('nombre',)} # Ayuda a generar el slug automático en el admin


# 🚀 2. Ahora sí registramos el ColaboradorEvento (Ya no dará error)
@admin.register(ColaboradorEvento)
class ColaboradorEventoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'evento', 'rol', 'fecha_asignacion')
    list_filter = ('rol',)
    search_fields = ('usuario__email', 'usuario__username', 'evento__nombre')
    
    # Como 'Evento' ya tiene 'search_fields' arriba, y 'User' (de Django) 
    # ya los tiene por defecto en su propio admin, esto funcionará perfecto.
    autocomplete_fields = ('evento', 'usuario')