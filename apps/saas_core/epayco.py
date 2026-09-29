"""AppDanza-only ePayco adapter. Verified TLS, timeouts, no SDK global patches.

One scheduler owns recurrence: AppDanza invoices + tokenized charges. Native
ePayco subscriptions are never created as well. Unknown outcomes reconcile;
they are not retried as a fresh charge. No PAN/CVV reaches these functions.
"""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.academias.locks import lock_tenant
from .models import PaymentAttempt, SaaSInvoice, ProviderEvent, ProviderEventResult
from .policy import BillingPolicy
from .jobs import enqueue
from .billing import settle

SAFE_FIELDS = ('x_cust_id_cliente', 'x_ref_payco', 'x_transaction_id', 'x_id_invoice',
    'x_id_factura', 'x_amount', 'x_currency_code', 'x_cod_transaction_state', 'x_test_request')


class ProviderError(Exception):
    pass


class ProviderUnavailable(ProviderError):
    pass


class UnknownOutcome(ProviderError):
    pass


def config():
    result = {key: getattr(settings, 'APPDANZA_EPAYCO_' + key, '') for key in
              ('PUBLIC_KEY', 'PRIVATE_KEY', 'CUSTOMER_ID', 'P_KEY')}
    if not all(result.values()):
        raise ProviderUnavailable('Falta la configuración ePayco propia de AppDanza.')
    result['TEST'] = getattr(settings, 'APPDANZA_EPAYCO_TEST', True)
    if not result['TEST'] and not getattr(settings, 'APPDANZA_EPAYCO_LIVE_ENABLED', False):
        raise ProviderUnavailable('Los cobros reales están deshabilitados.')
    return result


def signature(data, cfg):
    text = '^'.join(str(value) for value in (cfg['CUSTOMER_ID'], cfg['P_KEY'],
        data.get('x_ref_payco', ''), data.get('x_transaction_id', ''), data.get('x_amount', ''), data.get('x_currency_code', '')))
    return hashlib.sha256(text.encode()).hexdigest()


def validate_webhook(data):
    cfg = config()
    required = ('x_ref_payco', 'x_transaction_id', 'x_amount', 'x_currency_code', 'x_signature', 'x_cust_id_cliente', 'x_test_request')
    if any(not str(data.get(k, '')).strip() for k in required):
        raise ValidationError('Confirmación incompleta.')
    if str(data['x_cust_id_cliente']) != str(cfg['CUSTOMER_ID']) or not hmac.compare_digest(
            signature(data, cfg), str(data['x_signature']).lower()):
        raise ValidationError('Firma inválida.')
    flag = str(data['x_test_request']).lower()
    if flag not in ('true', 'false', '1', '0') or (flag in ('true', '1')) != cfg['TEST']:
        raise ValidationError('Modo de transacción incompatible.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', str(data['x_ref_payco'])):
        raise ValidationError('Referencia inválida.')
    return {k: str(data.get(k, ''))[:200] for k in SAFE_FIELDS}


@transaction.atomic
def receive_webhook(data):
    safe = validate_webhook(data)
    fingerprint = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
    event, created = ProviderEvent.objects.get_or_create(fingerprint=fingerprint,
        defaults={'reference': safe['x_ref_payco'], 'payload': safe})
    if created:
        ProviderEventResult.objects.create(event=event)
        enqueue('BILLING_WEBHOOK', {'event_id': event.pk}, key=f'provider-event:{event.pk}')
    return event


class EPaycoClient:
    API = 'https://api.secure.payco.co'
    VALIDATION = 'https://secure.epayco.co/validation/v1/reference/'

    def __init__(self, http=None):
        self.http = http or requests.Session()
        self.cfg = config()

    def _request(self, method, url, *, body=None, headers=None, mutation=False):
        try:
            response = self.http.request(method, url, json=body, headers=headers or {},
                timeout=(5, 20), allow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise UnknownOutcome('Respuesta del proveedor pendiente de conciliación.') if mutation else ProviderError('Proveedor no disponible.')
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (requests.RequestException, ValueError) as exc:
            raise UnknownOutcome('Resultado pendiente de conciliación.') if mutation else ProviderError('No se pudo consultar el proveedor.') from exc

    def call(self, path, body, *, mutation=True):
        auth = self._request('POST', self.API+'/v1/auth/login', body={
            'public_key': self.cfg['PUBLIC_KEY'], 'private_key': self.cfg['PRIVATE_KEY']},
            headers={'type': 'sdk-jwt', 'Content-Type': 'application/json'})
        token = auth.get('bearer_token')
        if not isinstance(token, str) or not token:
            raise ProviderError('No se pudo autenticar con el proveedor.')
        return self._request('POST', self.API+'/'+path, body={**body, 'test': self.cfg['TEST']},
            headers={'Authorization': 'Bearer '+token, 'type': 'sdk-jwt', 'Content-Type': 'application/json'}, mutation=mutation)

    def create_customer(self, *, token, name, email):
        if not token or len(token) > 150:
            raise ValidationError('Token de medio de pago inválido.')
        return self.call('payment/v1/customer/create', {'token_card': token, 'name': name,
                                                      'email': email, 'default': True})

    def charge(self, *, invoice, token, customer, document_type, document_number, name, email, ip):
        return self.call('payment/v1/charge/create', {'token_card': token, 'customer_id': customer,
            'doc_type': document_type, 'doc_number': document_number, 'name': name, 'email': email,
            'bill': invoice.reference, 'description': 'Servicios AppDanza', 'country': invoice.academia.pais,
            'value': str(invoice.payable_amount), 'currency': invoice.currency, 'dues': '1', 'ip': ip,
            'url_confirmation': settings.APPDANZA_PUBLIC_URL.rstrip('/')+'/billing/epayco/confirmation/',
            'method_confirmation': 'POST'})

    def lookup(self, reference):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', reference):
            raise ValidationError('Referencia inválida.')
        payload = self._request('GET', self.VALIDATION+quote(reference, safe=''))
        if payload.get('success') is not True or not isinstance(payload.get('data'), dict):
            raise ProviderError('La referencia aún no está disponible para conciliación.')
        return payload['data']


def process_provider_event(event_id, client=None):
    event = ProviderEvent.objects.get(pk=event_id)
    result = ProviderEventResult.objects.get(event=event)
    if result.state == 'PROCESSED':
        return
    # ePayco's signature does not cover state/invoice. Confirm those with a
    # server-to-server lookup; a valid amount signature alone cannot activate access.
    authoritative = (client or EPaycoClient()).lookup(event.reference)
    reference = str(authoritative.get('x_id_invoice') or authoritative.get('x_id_factura') or '')
    invoice = SaaSInvoice.objects.select_related('academia').filter(reference=reference).first()
    if not invoice:
        ProviderEventResult.objects.filter(pk=result.pk).update(state='REVIEW', reason='unknown_invoice')
        return
    cfg = config()
    try:
        amount = Decimal(str(authoritative.get('x_amount', '')))
    except InvalidOperation:
        raise ProviderError('Importe del proveedor inválido.')
    flag = str(authoritative.get('x_test_request', '')).lower()
    merchant = str(authoritative.get('x_cust_id_cliente') or authoritative.get('x_cliente_id_cliente') or '')
    if (merchant != str(cfg['CUSTOMER_ID']) or str(authoritative.get('x_ref_payco')) != event.reference or
        amount != (invoice.payment.amount if invoice.state == 'PAID' else invoice.payable_amount) or authoritative.get('x_currency_code', '').upper() != invoice.currency or
        flag not in ('true', 'false', '1', '0') or (flag in ('true', '1')) != cfg['TEST']):
        ProviderEventResult.objects.filter(pk=result.pk).update(state='REVIEW', reason='monetary_identity_mismatch')
        return
    status = str(authoritative.get('x_cod_transaction_state', ''))
    with transaction.atomic():
        lock_tenant(invoice.academia)
        invoice.refresh_from_db()
        attempt = invoice.attempts.filter(provider_reference=event.reference).order_by('-sequence').first()
        if attempt is None:
            # A timed-out request may obtain its reference only in confirmation.
            # Do not overwrite older failed attempts or another reference.
            attempt = invoice.attempts.filter(provider_reference='', state__in=('SUBMITTING', 'UNKNOWN')).order_by('-sequence').first()
        if status == '1':
            if invoice.state != 'PAID':
                settle(invoice, reference='EPAYCO:'+event.reference, amount=amount, currency=invoice.currency, source='EPAYCO')
            elif invoice.payment.provider_reference != 'EPAYCO:'+event.reference:
                ProviderEventResult.objects.filter(pk=result.pk).update(state='REVIEW', reason='extra_payment')
                return
            if attempt:
                PaymentAttempt.objects.filter(pk=attempt.pk).update(state='SUCCEEDED', provider_reference=event.reference, updated_at=timezone.now())
        elif status in ('2', '4', '9', '10', '11') and invoice.state != 'PAID':
            if attempt and attempt.state != 'SUCCEEDED':
                PaymentAttempt.objects.filter(pk=attempt.pk).update(state='FAILED', provider_reference=event.reference, updated_at=timezone.now())
        elif invoice.state != 'PAID':
            if attempt and attempt.state != 'SUCCEEDED':
                PaymentAttempt.objects.filter(pk=attempt.pk).update(state='PENDING', provider_reference=event.reference, updated_at=timezone.now())
        ProviderEventResult.objects.filter(pk=result.pk).update(state='PROCESSED', processed_at=timezone.now(), reason='')


def reconcile_reference(reference, client=None):
    """Read-only provider lookup, followed by the same verified ledger transition.

    This administrative recovery path sends no charge and accepts no operator-
    supplied payment status. Unknown outcomes without a reference stay unknown.
    """
    provider = client or EPaycoClient()
    data = provider.lookup(reference)
    safe = {key: str(data.get(key, ''))[:200] for key in SAFE_FIELDS}
    fingerprint = hashlib.sha256(('reconcile:'+json.dumps(safe, sort_keys=True)).encode()).hexdigest()
    with transaction.atomic():
        event, created = ProviderEvent.objects.get_or_create(fingerprint=fingerprint,
            defaults={'reference': reference, 'payload': safe})
        if created:
            ProviderEventResult.objects.create(event=event)
    process_provider_event(event.pk, provider)
    return ProviderEventResult.objects.get(event=event)
