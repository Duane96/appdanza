"""Immediate display and durable email delivery of event QR credentials.

A QR is issued at registration; payment state is always checked during admission.
No SaaS fee is metered merely because this email or QR exists.
"""
import base64
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import qrcode
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils.text import slugify

from apps.saas_core.jobs import enqueue
from .models import ReciboEvento


def qr_png(code):
    code_image = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=4,
    )
    code_image.add_data(str(code))
    code_image.make(fit=True)
    image = code_image.make_image(fill_color='black', back_color='white')
    stream = BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def qr_data_uri(code):
    """Immediate lightweight fallback while the private branded PNG is processed."""
    return 'data:image/png;base64,' + base64.b64encode(qr_png(code)).decode('ascii')


def queue_ticket_email(receipt, stage, *, version='first'):
    """Persist first, try SMTP after commit; recover failures with the job worker."""
    if not receipt.comprador_correo:
        return None
    job = enqueue(
        'EVENT_TICKET_EMAIL', {'receipt_id': receipt.pk, 'stage': stage},
        tenant=receipt.evento.academia,
        key=f'event-ticket-email:{receipt.pk}:{stage}:{version}',
    )
    from apps.saas_core.jobs import run_now
    transaction.on_commit(lambda job_id=job.pk: run_now(job_id))
    return job


def deliver_event_tickets(receipt_id, tenant_id, stage):
    """Mail the actual scan-ready PNG codes even if branded images are not ready."""
    receipt = ReciboEvento.objects.select_related(
        'evento__academia',
    ).get(pk=receipt_id, evento__academia_id=tenant_id)
    if not receipt.comprador_correo or receipt.anulado:
        return
    if stage == 'REGISTERED' and receipt.payment_status not in ('PENDING', 'REVIEW'):
        return
    if stage != 'REGISTERED' and receipt.payment_status not in ('CONFIRMED', 'LEGACY'):
        return
    tickets = list(receipt.boletas_qr.filter(revoked_at=None).order_by('pk'))
    if not tickets:
        raise RuntimeError('No event QR credentials to deliver')

    event = receipt.evento
    if stage == 'REGISTERED':
        subject = f'Inscripción recibida - {event.nombre}'
        instruction = (
            'Adjuntamos tus QR desde ahora. El pago sigue pendiente de verificación '
            'y los códigos NO autorizan ingreso hasta que el organizador lo confirme.'
        )
    elif stage == 'REISSUED':
        subject = f'Tus entradas para {event.nombre}'
        instruction = 'Adjuntamos tus QR vigentes. Conserva estos códigos para ingresar al evento.'
    elif stage == 'RECOVERED':
        subject = f'Tus entradas para {event.nombre}'
        instruction = 'Te reenviamos tus QR de acceso. Son válidos para ingresar al evento.'
    else:
        subject = f'Pago confirmado: tus QR activos - {event.nombre}'
        instruction = 'Tu pago ya está confirmado y estos QR pueden utilizarse para entrar.'

    text = (
        f'Hola, {receipt.comprador_nombre}.\n\n'
        f'Evento: {event.nombre}\n'
        f'Registro: {receipt.numero_recibo}\n'
        f'{instruction}\n\n'
        'Cada persona tiene un QR individual. Si tu pase admite varios días, '
        'usa el mismo QR un máximo de una vez por día, hasta agotar los accesos.\n'
        'Conserva los archivos adjuntos. No compartas estos códigos públicamente.'
    )
    message = EmailMultiAlternatives(
        subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL,
        to=[receipt.comprador_correo],
    )
    if len(tickets) <= 8:
        for ordinal, ticket in enumerate(tickets, start=1):
            message.attach(
                f'entrada-{ordinal:02d}.png', qr_png(ticket.codigo_unico), 'image/png',
            )
    else:
        archive = BytesIO()
        with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as packed:
            for ordinal, ticket in enumerate(tickets, start=1):
                packed.writestr(f'entrada-{ordinal:03d}.png', qr_png(ticket.codigo_unico))
        message.attach(
            f'entradas-{slugify(event.nombre) or "evento"}.zip',
            archive.getvalue(), 'application/zip',
        )
    message.send(fail_silently=False)
