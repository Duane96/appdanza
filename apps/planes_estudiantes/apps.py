# apps/planes_estudiantes/apps.py
from django.apps import AppConfig

class PlanesEstudiantesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.planes_estudiantes'  # ⚠️ El prefijo 'apps.' es obligatorio