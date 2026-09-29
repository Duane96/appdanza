"""Receipt links carry an expiring, purpose-bound capability, never just an ID."""
from django.core import signing
from django.urls import reverse
from apps.academias.authorization import can

SALT = 'appdanza.event-receipt.v1'
MAX_AGE = 60 * 60 * 24 * 30


def receipt_token(receipt):
    return signing.dumps({'receipt': receipt.pk, 'tenant': receipt.evento.academia_id}, salt=SALT)


def receipt_url(receipt):
    return reverse('eventos:registro_exito', kwargs={'slug_academia': receipt.evento.academia.slug,
                   'recibo_id': receipt.pk}) + '?token=' + receipt_token(receipt)


def can_read_receipt(request, receipt):
    if can(request.user, receipt.evento.academia, 'events.manage', receipt.evento):
        return True
    try:
        data = signing.loads(request.GET.get('token', ''), salt=SALT, max_age=MAX_AGE)
        return data == {'receipt': receipt.pk, 'tenant': receipt.evento.academia_id}
    except signing.BadSignature:
        return False
