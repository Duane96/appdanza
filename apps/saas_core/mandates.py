from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from .models import PaymentMandate
from .policy import BillingPolicy
from .billing_scheduler import cipher
from .epayco import EPaycoClient
from .audit import record


def register_mandate(tenant, actor, *, token, document_type, document_number, consent, ip, client=None):
    authorize(actor, tenant, 'billing.manage')
    policy = BillingPolicy(tenant)
    if not consent or not policy.can_invoice:
        raise ValidationError('Se requiere un contrato aceptado y autorización expresa de cargos.')
    if document_type not in ('CC', 'CE', 'NIT', 'PP', 'DNI') or not document_number.strip() or len(document_number) > 50:
        raise ValidationError('Documento del titular inválido.')
    if not actor.email or not token or len(token) > 150:
        raise ValidationError('Se requiere un correo y un token de medio de pago válido.')
    encrypted = cipher().encrypt(token.encode()).decode()
    provider = client or EPaycoClient()
    # ePayco receives the card directly in its JS tokenization. This backend
    # accepts only its opaque token; it cannot receive PAN/CVV fields.
    response = provider.create_customer(token=token, name=actor.get_full_name() or actor.username, email=actor.email)
    data = response.get('data')
    customer = data.get('customerId') if isinstance(data, dict) else None
    if response.get('status') is not True and response.get('success') is not True:
        raise ValidationError('El proveedor no confirmó el registro del medio de pago.')
    if not isinstance(customer, str) or not customer:
        raise ValidationError('El proveedor requiere conciliación del registro del cliente.')
    with transaction.atomic():
        lock_tenant(tenant)
        policy = BillingPolicy(tenant)
        if not policy.can_invoice:
            raise ValidationError('El contrato cambió durante la solicitud; no se habilitarán cargos.')
        mandate, _ = PaymentMandate.objects.update_or_create(academia=tenant, defaults={
            'customer_id': customer, 'encrypted_token': encrypted, 'document_type': document_type,
            'document_number': document_number, 'payer_name': actor.get_full_name() or actor.username,
            'email': actor.email, 'consent_ip': ip, 'consent_at': timezone.now(), 'revoked_at': None})
        policy.account.automatic_charges_authorized = True
        policy.account.save(update_fields=['automatic_charges_authorized'])
        record(tenant, actor, 'billing.mandate.authorized', mandate.pk)
    return mandate


@transaction.atomic
def revoke_mandate(tenant, actor):
    authorize(actor, tenant, 'billing.manage')
    lock_tenant(tenant)
    policy = BillingPolicy(tenant)
    if policy.account:
        policy.account.automatic_charges_authorized = False
        policy.account.save(update_fields=['automatic_charges_authorized'])
    PaymentMandate.objects.filter(academia=tenant, revoked_at=None).update(revoked_at=timezone.now(), encrypted_token='')
    record(tenant, actor, 'billing.mandate.revoked', tenant.pk)
