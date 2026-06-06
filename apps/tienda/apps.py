# apps/asistencias/apps.py
from django.apps import AppConfig

class TiendaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.tienda'  # ⚠️ Obligatorio el prefijo 'apps.'