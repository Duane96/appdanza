from django.db.models import F
from django.core.exceptions import ValidationError
from .models import Academia


def lock_tenant(tenant):
    """Call first inside atomic: row lock on PG, writer reservation on SQLite."""
    if not Academia.unfiltered_objects.filter(pk=tenant.pk).update(activo=F('activo')):
        raise ValidationError('Academia no disponible.')
