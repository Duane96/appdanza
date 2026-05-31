# apps/asistencias/apps.py
from django.apps import AppConfig

class AsistenciasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.asistencias'  # ⚠️ Obligatorio el prefijo 'apps.'