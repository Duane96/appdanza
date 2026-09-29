from django.apps import AppConfig


class AcademiasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.academias'

    def ready(self):
        from apps.academias import signals  # noqa: F401
