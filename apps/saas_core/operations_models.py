import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    academia = models.ForeignKey('academias.Academia', null=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    service = models.CharField(max_length=80, blank=True)
    action = models.CharField(max_length=80)
    resource = models.CharField(max_length=120)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Los eventos de auditoría son inmutables.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('La auditoría no se elimina desde la aplicación.')


class DurableJob(models.Model):
    class State(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        PROCESSING = 'PROCESSING', 'Procesando'
        DONE = 'DONE', 'Completado'
        FAILED = 'FAILED', 'Falló'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academia = models.ForeignKey('academias.Academia', null=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    dedupe_key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True)
    lease_token = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=120, blank=True)

    class Meta:
        indexes = [models.Index(fields=['state', 'available_at'], name='job_ready_idx')]
