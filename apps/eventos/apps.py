# apps/eventos/apps.py
from django.apps import AppConfig

class EventosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.eventos' # 👈 Crucial para que Django lo busque dentro de la carpeta apps

    def ready(self):
        # 🚀 Conectamos los detonantes en el arranque de Django
        import apps.eventos.signals