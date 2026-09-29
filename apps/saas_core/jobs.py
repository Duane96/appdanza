"""Durable at-least-once outbox. Economic handlers must also be idempotent."""
import base64
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import F, Q
from django.utils import timezone
from gestoracademia.tenants import set_current_tenant, clear_current_tenant
from .models import DurableJob


def enqueue(kind, payload, *, tenant=None, key=None):
    return DurableJob.objects.get_or_create(dedupe_key=key or str(uuid.uuid4()),
        defaults={'kind': kind, 'payload': payload, 'academia': tenant})[0]


def claim():
    now = timezone.now()
    DurableJob.objects.filter(state='PROCESSING', lease_until__lt=now, attempts__gte=5).update(
        state='FAILED', lease_until=None, last_error='LeaseExpired')
    eligible = Q(state='PENDING', available_at__lte=now) | Q(state='PROCESSING', lease_until__lt=now)
    ids = list(DurableJob.objects.filter(eligible, attempts__lt=5).order_by('available_at').values_list('pk', flat=True)[:10])
    for pk in ids:
        token = uuid.uuid4()
        if DurableJob.objects.filter(eligible, pk=pk, attempts__lt=5).update(state='PROCESSING',
                lease_token=token, lease_until=now + timedelta(minutes=5), attempts=F('attempts') + 1):
            return DurableJob.objects.select_related('academia').get(pk=pk, lease_token=token)
    return None


def handle(job):
    data = job.payload
    if job.kind == 'EMAIL':
        message = EmailMultiAlternatives(subject=data['subject'], body=data.get('text', 'Consulta la versión HTML.'),
            from_email=settings.DEFAULT_FROM_EMAIL, to=data['to'])
        if data.get('html'):
            message.attach_alternative(data['html'], 'text/html')
        if data.get('attachment'):
            item = data['attachment']
            message.attach(item['name'], base64.b64decode(item['data']), item['type'])
        message.send(fail_silently=False)
    elif job.kind == 'EVENT_QR':
        from apps.eventos.models import EntradaQR
        from apps.eventos.signals import render_ticket_image
        ticket = EntradaQR.objects.select_related('recibo__evento__academia').get(pk=data['ticket_id'],
            recibo__evento__academia_id=job.academia_id)
        if not ticket.imagen_qr:
            render_ticket_image(EntradaQR, ticket, True)
    elif job.kind == 'BILLING_WEBHOOK':
        from .epayco import process_provider_event
        process_provider_event(data['event_id'])
    elif job.kind == 'BILLING_CHARGE':
        from .billing_scheduler import charge_attempt
        charge_attempt(data['attempt_id'])
    else:
        raise ValueError('unsupported_job_kind')


def run_one():
    job = claim()
    if job is None:
        return False
    try:
        set_current_tenant(job.academia)
        handle(job)
    except Exception as exc:
        # Exception messages can contain SMTP recipients or provider secrets.
        DurableJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(
            state='FAILED' if job.attempts >= 5 else 'PENDING', lease_until=None,
            available_at=timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** job.attempts)),
            last_error=type(exc).__name__)
    else:
        DurableJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(
            state='DONE', completed_at=timezone.now(), lease_until=None, last_error='', payload={})
    finally:
        clear_current_tenant()
    return True
