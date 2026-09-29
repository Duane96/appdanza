"""Transactional invoice, usage and dunning operations; no provider I/O here."""
import calendar
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from .models import (BillingAccount, CommercialSubscription, PlanVersion, EventFeeRate,
    SaaSInvoice, InvoiceLine, UsageEntry, UsageAllocation, SaaSPayment, SaaSCredit, SaaSRefund)
from .policy import BillingPolicy
from .audit import record
from .jobs import enqueue

ZERO = Decimal('0.00')


def add_months(value, months):
    offset = value.year*12 + value.month-1 + months
    year, month = divmod(offset, 12)
    month += 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def effective_rate(event, at):
    policy = BillingPolicy(event.academia)
    rates = EventFeeRate.objects.filter(effective_at__lte=at, currency=event.academia.divisa).order_by('-effective_at', '-pk')
    rate = rates.filter(scope='EVENT', evento=event).first() or rates.filter(scope='TENANT', academia=event.academia).first()
    if not rate and policy.subscription:
        rate = rates.filter(scope='PLAN', plan_version=policy.subscription.plan_version).first()
    return rate or rates.filter(scope='GLOBAL').first()


def meter_admission(admission):
    """Only called from confirmation, in its transaction. Never backfill sales."""
    receipt = admission.receipt
    tenant = receipt.evento.academia
    existing = UsageEntry.objects.filter(admission=admission).first()
    if existing:
        return existing
    policy = BillingPolicy(tenant)
    rate, amount, reason = None, ZERO, 'NO_COMMERCIAL_UNIT'
    if policy.exempt:
        reason = 'BILLING_EXEMPT'
    elif not admission.commercial_unit:
        reason = 'NO_COMMERCIAL_UNIT'
    elif receipt.payment_status != 'CONFIRMED' or receipt.anulado:
        reason = 'UNCONFIRMED'
    elif receipt.monto_total <= ZERO:
        reason = 'COMPLIMENTARY_ADMISSION'
    elif not policy.can_invoice:
        reason = 'NO_ACCEPTED_CONTRACT'
    else:
        rate = effective_rate(receipt.evento, timezone.now())
        if rate:
            units = receipt.price_snapshot['commercial_units']
            # Per-admission pricing snapshot; currency precision is explicit.
            amount = (rate.fixed_per_admission + receipt.monto_total / Decimal(units) * rate.percentage / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            reason = 'CONFIRMED_ADMISSION' if amount else 'ZERO_RATE'
        else:
            reason = 'NO_RATE'
    return UsageEntry.objects.create(academia=tenant, admission=admission, rate=rate, amount=amount,
        currency=tenant.divisa, billable=amount > ZERO, reason=reason,
        snapshot={'receipt_id': receipt.pk, 'event_id': receipt.evento_id, 'ordinal': admission.ordinal,
                  'fixed': str(rate.fixed_per_admission) if rate else '0', 'percentage': str(rate.percentage) if rate else '0'})


@transaction.atomic
def invoice_subscription(tenant, period_start, period_end):
    lock_tenant(tenant)
    policy = BillingPolicy(tenant)
    if not policy.can_invoice or policy.subscription.state in ('TRIAL', 'CANCELLED'):
        return None
    subscription = policy.subscription
    if period_start < subscription.accepted_at or period_end <= period_start:
        raise ValidationError('No se facturan períodos anteriores a la aceptación del contrato.')
    version = subscription.pending_plan_version if subscription.pending_plan_version_id and period_start >= subscription.period_end else subscription.plan_version
    if version.amount <= ZERO:
        return None
    key = f'subscription:{subscription.pk}:{period_start.isoformat()}:{period_end.isoformat()}'
    invoice, created = SaaSInvoice.objects.get_or_create(source_key=key, defaults={
        'academia': tenant, 'subscription': subscription, 'reference': 'AD-'+uuid.uuid4().hex,
        'period_start': period_start, 'period_end': period_end, 'currency': version.currency,
        'amount': version.amount, 'due_at': period_start})
    if created:
        InvoiceLine.objects.create(invoice=invoice, description=version.name, kind='SUBSCRIPTION', amount=version.amount,
            snapshot={'version_id': version.pk, 'interval_months': version.interval_months, 'currency': version.currency})
        record(tenant, None, 'billing.invoice.created', invoice.pk, after={'amount': invoice.amount}, service='billing')
    return invoice


@transaction.atomic
def close_usage(tenant, start, end):
    lock_tenant(tenant)
    if not BillingPolicy(tenant).can_invoice:
        return None
    if end <= start or end > timezone.now():
        raise ValidationError('El período de consumo debe estar cerrado.')
    key = f'usage:{tenant.pk}:{start.isoformat()}:{end.isoformat()}'
    existing = SaaSInvoice.objects.filter(source_key=key).first()
    if existing:
        return existing
    entries = list(UsageEntry.objects.filter(academia=tenant, billable=True, allocation=None,
        occurred_at__gte=start, occurred_at__lt=end).exclude(saascredit__isnull=False))
    if not entries:
        return None
    currencies = {item.currency for item in entries}
    if len(currencies) != 1:
        raise ValidationError('Cierra cada moneda por separado; no se convierten importes implícitamente.')
    total = sum((item.amount for item in entries), ZERO)
    invoice = SaaSInvoice.objects.create(academia=tenant, reference='AD-'+uuid.uuid4().hex, source_key=key,
        period_start=start, period_end=end, currency=currencies.pop(), amount=total, due_at=timezone.now())
    for item in entries:
        line = InvoiceLine.objects.create(invoice=invoice, description=f'Registro confirmado #{item.admission_id}',
            kind='USAGE', amount=item.amount, snapshot=item.snapshot)
        UsageAllocation.objects.create(usage=item, invoice_line=line)
    record(tenant, None, 'billing.usage.closed', invoice.pk, after={'amount': total}, service='billing')
    return invoice


@transaction.atomic
def settle(invoice, *, reference, amount, currency, source, actor=None):
    lock_tenant(invoice.academia)
    invoice.refresh_from_db()
    amount = Decimal(str(amount))
    existing = SaaSPayment.objects.filter(provider_reference=reference).first()
    if existing:
        if existing.invoice_id != invoice.pk or existing.amount != amount or existing.currency != currency.upper():
            raise ValidationError('La referencia de pago ya pertenece a otra cuenta.')
        return existing
    if amount != invoice.payable_amount or amount <= ZERO or currency.upper() != invoice.currency or not reference:
        raise ValidationError('El importe, la moneda o la referencia no corresponden a la cuenta.')
    if invoice.state != 'OPEN' or BillingPolicy(invoice.academia).exempt:
        raise ValidationError('Esta cuenta no admite otro cobro.')
    payment = SaaSPayment.objects.create(invoice=invoice, provider_reference=reference, amount=amount,
                                         currency=currency, source=source)
    invoice.state, invoice.paid_at = 'PAID', timezone.now()
    invoice.save(update_fields=['state', 'paid_at'])
    if invoice.subscription_id:
        subscription = invoice.subscription
        if subscription.last_paid_period_end is None or invoice.period_end > subscription.last_paid_period_end:
            subscription.last_paid_period_end = invoice.period_end
            subscription.period_start, subscription.period_end = invoice.period_start, invoice.period_end
            line = invoice.lines.filter(kind='SUBSCRIPTION').first()
            if line and line.snapshot.get('version_id'):
                subscription.plan_version_id = line.snapshot['version_id']
                if subscription.pending_plan_version_id == subscription.plan_version_id:
                    subscription.pending_plan_version = None
            if subscription.state != 'CANCELLED':
                subscription.state = 'ACTIVE'
            subscription.save()
    record(invoice.academia, actor, 'billing.payment.confirmed', invoice.pk, after={'amount': amount}, service=source)
    update_dunning(invoice.academia)
    return payment


@transaction.atomic
def credit_refunded_admissions(receipt, refund, actor):
    """Reverse only metered new admissions, preserving original usage and invoices.

    A cancelled credential alone is not evidence of returned money. This service
    is called only after the event's full, documented refund is recorded.
    """
    tenant = receipt.evento.academia
    lock_tenant(tenant)
    for usage in UsageEntry.objects.filter(admission__receipt=receipt, billable=True):
        allocation = UsageAllocation.objects.select_related('invoice_line__invoice').filter(usage=usage).first()
        invoice = allocation.invoice_line.invoice if allocation else None
        credit, created = SaaSCredit.objects.get_or_create(usage=usage, defaults={
            'academia': tenant, 'invoice': invoice, 'amount': usage.amount, 'currency': usage.currency,
            'reference': f'event-refund:{refund.pk}:usage:{usage.pk}', 'reason': refund.reason[:255]})
        if created:
            record(tenant, actor, 'billing.usage.credited', credit.pk, after={'amount': credit.amount}, reason=refund.reason)
        if invoice and invoice.state == 'OPEN' and invoice.payable_amount == ZERO:
            invoice.state = 'VOID'
            invoice.save(update_fields=['state'])
    update_dunning(tenant)


@transaction.atomic
def record_saas_refund(payment, actor, *, amount, reference, reason):
    """Record a verified provider/bank refund; this function never sends money."""
    authorize(actor, None, 'platform.manage')
    lock_tenant(payment.invoice.academia)
    amount = Decimal(str(amount))
    existing = SaaSRefund.objects.filter(provider_reference=reference).first()
    if existing:
        if existing.payment_id != payment.pk or existing.amount != amount:
            raise ValidationError('La referencia pertenece a otra devolución.')
        return existing
    returned = SaaSRefund.objects.filter(payment=payment).aggregate(total=Sum('amount'))['total'] or ZERO
    if not reference.strip() or not reason.strip() or amount <= ZERO or returned + amount > payment.amount:
        raise ValidationError('Verifica el importe, la evidencia y el saldo de la devolución.')
    result = SaaSRefund.objects.create(payment=payment, amount=amount, provider_reference=reference, reason=reason)
    record(payment.invoice.academia, actor, 'billing.refund.recorded', result.pk,
           after={'amount': amount}, reason=reason)
    return result


@transaction.atomic
def cancel_subscription(tenant, actor):
    authorize(actor, tenant, 'billing.manage')
    lock_tenant(tenant)
    subscription = CommercialSubscription.objects.filter(academia=tenant).first()
    if subscription is None:
        raise ValidationError('No hay una suscripción comercial para cancelar.')
    if subscription.provider == 'EPAYCO' and subscription.provider_subscription_id:
        raise ValidationError('Esta suscripción externa requiere cancelar primero el mandato en el proveedor.')
    subscription.cancel_at_period_end = True
    subscription.save(update_fields=['cancel_at_period_end'])
    record(tenant, actor, 'billing.subscription.cancel_requested', subscription.pk)


@transaction.atomic
def update_dunning(tenant, at=None):
    lock_tenant(tenant)
    policy = BillingPolicy(tenant)
    if policy.exempt or not policy.subscription:
        return 'EXEMPT'
    now, subscription = at or timezone.now(), policy.subscription
    if subscription.cancel_at_period_end and now >= subscription.period_end:
        subscription.state, subscription.cancelled_at = 'CANCELLED', now
        subscription.save(update_fields=['state', 'cancelled_at'])
        return 'CANCELLED'
    unpaid = SaaSInvoice.objects.filter(academia=tenant, state='OPEN', due_at__lt=now).order_by('due_at').first()
    if unpaid is None and subscription.state in ('PAST_DUE', 'LIMITED', 'SUSPENDED') and subscription.period_end >= now:
        subscription.state = 'ACTIVE'
        subscription.save(update_fields=['state'])
    if unpaid is None or subscription.state == 'CANCELLED':
        return subscription.state
    overdue = (now-unpaid.due_at).days
    new_state = 'SUSPENDED' if overdue >= policy.account.suspend_after_days else 'LIMITED' if overdue >= policy.account.grace_days else 'PAST_DUE'
    if subscription.state != new_state:
        before = subscription.state
        subscription.state = new_state
        subscription.save(update_fields=['state'])
        record(tenant, None, 'billing.subscription.dunning', subscription.pk,
               before={'state': before}, after={'state': new_state}, service='billing')
        if policy.account.billing_email:
            enqueue('EMAIL', {'subject': 'Tu cuenta AppDanza requiere atención', 'to': [policy.account.billing_email],
                'text': 'Hay un pago pendiente. Revisa Mi plan y facturación. Tus datos se conservan.'},
                tenant=tenant, key=f'dunning:{unpaid.pk}:{new_state}')
    return new_state
