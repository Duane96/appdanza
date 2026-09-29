from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import models


class ScopedModel(models.Model):
    """Validate cross-resource tenant/event consistency even outside a form."""
    class Meta:
        abstract = True

    def validate_scope(self):
        from .authorization import tenant_id_for
        tenant_id = tenant_id_for(self)
        event_id = getattr(self, 'evento_id', None)
        if not event_id and getattr(self, 'fase_id', None):
            event_id = self.fase.evento_id
        errors = {}
        for field in self._meta.fields:
            if not field.is_relation or field.many_to_many or not getattr(self, field.attname, None):
                continue
            try:
                related = getattr(self, field.name)
            except ObjectDoesNotExist:
                continue  # Django validates missing FK values separately.
            related_tenant = tenant_id_for(related)
            if tenant_id and related_tenant and related_tenant != tenant_id:
                errors[field.name] = 'El registro debe pertenecer a esta academia.'
            related_event = getattr(related, 'evento_id', None)
            if event_id and related_event and related_event != event_id:
                errors[field.name] = 'El registro debe pertenecer a este evento.'
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self.validate_scope()

    def save(self, *args, **kwargs):
        self.validate_scope()
        return super().save(*args, **kwargs)
