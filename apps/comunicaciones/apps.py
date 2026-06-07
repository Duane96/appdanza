# apps/comunicaciones/apps.py
from django.apps import AppConfig

class ComunicacionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.comunicaciones' # 👈 Crucial para que Django lo busque dentro de la carpeta apps
