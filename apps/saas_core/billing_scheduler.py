"""Single AppDanza recurrence owner. Durable claims precede network operations."""
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from cryptography.fernet import Fernet, InvalidToken
from apps.academias.locks import lock_tenant
from .models import BillingAccount, CommercialSubscription, PaymentAttempt, PaymentMandate, SaaSInvoice, UsageEntry
from .policy import BillingPolicy
from .billing import invoice_subscription, update_dunning, add_months, close_usage
from .jobs import enqueue
from .epayco import EPaycoClient, ProviderError, ProviderUnavailable, UnknownOutcome, config


def cipher():
    key = settings.APPDANZA_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ProviderUnavailable('Falta la clave privada de cifrado de mandatos.')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise ProviderUnavailable('La clave de cifrado requiere configuración.')


@transaction.atomic
def schedule_attempt(invoice, *, manual=False):
    lock_tenant(invoice.academia)
    policy = BillingPolicy(invoice.academia)
    invoice.refresh_from_db()
    if invoice.state != 'OPEN' or not policy.can_automatically_charge:
        return None
    if not settings.APPDANZA_AUTOMATIC_BILLING_ENABLED:
        return None
    if policy.subscription.cancel_at_period_end:
        return None
    if not PaymentMandate.objects.filter(academia=invoice.academia, revoked_at=None).exists():
        return None
    last = invoice.attempts.order_by('-sequence').first()
    if last:
        if last.state != 'FAILED':
            return last  # Includes UNKNOWN/SUBMITTING: reconcile, never charge twice.
        retry_days = sorted(set(int(day) for day in policy.account.retry_days if int(day) > 0))
        if last.sequence > len(retry_days):
            return last
        retry_at = invoice.due_at+timedelta(days=retry_days[last.sequence-1])
        if timezone.now() < retry_at:
            return last
    attempt = PaymentAttempt.objects.create(invoice=invoice, sequence=last.sequence+1 if last else 1)
    enqueue('BILLING_CHARGE', {'attempt_id': str(attempt.pk)}, tenant=invoice.academia,
            key=f'charge-attempt:{attempt.pk}')
    return attempt


def charge_attempt(pk, client=None):
    # Validate configuration before the durable claim: missing credentials don't
    # create an uncertain charge. The request itself happens outside DB locks.
    provider = client or EPaycoClient()
    encryption = cipher()
    with transaction.atomic():
        attempt = PaymentAttempt.objects.select_related('invoice__academia').get(pk=pk)
        invoice = attempt.invoice
        lock_tenant(invoice.academia)
        attempt.refresh_from_db()
        policy = BillingPolicy(invoice.academia)
        if attempt.state != 'CREATED' or invoice.state != 'OPEN':
            return
        if not settings.APPDANZA_AUTOMATIC_BILLING_ENABLED or not policy.can_automatically_charge or policy.subscription.cancel_at_period_end:
            return
        mandate = PaymentMandate.objects.filter(academia=invoice.academia, revoked_at=None).first()
        if not mandate:
            return
        token = encryption.decrypt(mandate.encrypted_token.encode()).decode()
        PaymentAttempt.objects.filter(pk=pk, state='CREATED').update(state='SUBMITTING', updated_at=timezone.now())
    try:
        response = provider.charge(invoice=invoice, token=token, customer=mandate.customer_id,
            document_type=mandate.document_type, document_number=mandate.document_number,
            name=mandate.payer_name, email=mandate.email, ip=mandate.consent_ip)
        data = response.get('data', {})
        reference = str(data.get('ref_payco') or data.get('x_ref_payco') or '') if isinstance(data, dict) else ''
        if not reference:
            raise UnknownOutcome('El proveedor no devolvió una referencia conciliable.')
    except ProviderError:
        PaymentAttempt.objects.filter(pk=pk, state='SUBMITTING').update(state='UNKNOWN', failure_code='reconcile_required', updated_at=timezone.now())
        return
    PaymentAttempt.objects.filter(pk=pk, state='SUBMITTING').update(state='PENDING', provider_reference=reference, updated_at=timezone.now())
    # Only a signed webhook plus an authoritative query can settle an invoice.


def tick():
    now = timezone.now()
    # Never scan legacy academy receipts, admissions, or raw QR counts for billing.
    for subscription in CommercialSubscription.objects.select_related('academia', 'plan_version').filter(
            academia__billing_account__mode='PAID').exclude(state='CANCELLED'):
        tenant = subscription.academia
        # Entries exist only for new confirmed admissions. Closing this ledger
        # cannot turn legacy receipts/QRs into retroactive charges.
        first_usage = UsageEntry.objects.filter(academia=tenant, billable=True, allocation=None,
            saascredit=None).order_by('occurred_at').first()
        if first_usage:
            start = timezone.localtime(first_usage.occurred_at).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            current_month = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while start < current_month:
                end = add_months(start, 1)
                close_usage(tenant, start, end)
                start = end
        update_dunning(tenant, now)
        subscription.refresh_from_db()
        if subscription.state == 'CANCELLED' or subscription.cancel_at_period_end:
            continue
        if subscription.period_end <= now and subscription.state != 'TRIAL':
            # One outstanding next period, never catch-up historical invoices.
            start = subscription.period_end
            next_version = subscription.pending_plan_version or subscription.plan_version
            end = add_months(start, next_version.interval_months)
            if end > now:
                invoice_subscription(tenant, start, end)
        for invoice in SaaSInvoice.objects.filter(academia=tenant, state='OPEN'):
            schedule_attempt(invoice)
