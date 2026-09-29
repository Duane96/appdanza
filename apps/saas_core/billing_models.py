"""AppDanza's commercial ledger, separate from every academy's own receipts."""
import uuid
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.academias.scoped_model import ScopedModel


class ImmutableModel(ScopedModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Crea una nueva versión; este registro es inmutable.')
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Este registro forma parte del historial comercial.')


class BillingAccount(ScopedModel):
    class Mode(models.TextChoices):
        INTERNAL = 'INTERNAL', 'Interno / exento permanente'
        COMPLIMENTARY = 'COMPLIMENTARY', 'Acceso concedido sin cobro'
        TRIAL = 'TRIAL', 'Prueba sin cobro automático'
        PAID = 'PAID', 'Contrato comercial'
        LEGACY = 'LEGACY', 'Histórico / pendiente de contratación'

    academia = models.OneToOneField('academias.Academia', on_delete=models.PROTECT, related_name='billing_account')
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.LEGACY)
    grant_until = models.DateTimeField(null=True, blank=True)
    grant_features = models.JSONField(default=dict)
    grant_reason = models.CharField(max_length=255, blank=True)
    legacy_snapshot = models.JSONField(default=dict, blank=True)
    automatic_charges_authorized = models.BooleanField(default=False)
    billing_email = models.EmailField(blank=True)
    grace_days = models.PositiveSmallIntegerField(default=7)
    suspend_after_days = models.PositiveSmallIntegerField(default=21)
    retry_days = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        if self.mode != self.Mode.PAID and self.automatic_charges_authorized:
            raise ValidationError('Sólo un contrato comercial puede autorizar cargos automáticos.')
        if self.suspend_after_days < self.grace_days:
            raise ValidationError('La suspensión debe ser posterior al período de gracia.')

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(academia_id=self.academia_id).exists():
            raise ValidationError('La política comercial no puede trasladarse a otra academia.')
        if self.pk and type(self).objects.filter(pk=self.pk, mode='INTERNAL').exists() and self.mode != 'INTERNAL':
            raise ValidationError('La exención del tenant interno es permanente.')
        self.clean()
        return super().save(*args, **kwargs)


class PlanVersion(ImmutableModel):
    plan = models.ForeignKey('saas_core.PlanSaaS', on_delete=models.PROTECT, related_name='versions')
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='COP')
    interval_months = models.PositiveSmallIntegerField(default=1)
    features = models.JSONField(default=dict)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f'{self.name} v{self.version} — {self.amount} {self.currency} / {self.interval_months} mes(es)'

    class Meta:
        constraints = [models.UniqueConstraint(fields=['plan', 'version'], name='plan_version_unique'),
                       models.CheckConstraint(condition=models.Q(amount__gte=0), name='plan_amount_nonnegative'),
                       models.CheckConstraint(condition=models.Q(interval_months__gte=1), name='plan_interval_positive')]


class CommercialSubscription(ScopedModel):
    class State(models.TextChoices):
        TRIAL = 'TRIAL', 'En prueba'
        ACTIVE = 'ACTIVE', 'Activa'
        PAST_DUE = 'PAST_DUE', 'Pago pendiente / gracia'
        LIMITED = 'LIMITED', 'Operación limitada'
        SUSPENDED = 'SUSPENDED', 'Suspendida'
        CANCELLED = 'CANCELLED', 'Cancelada'

    academia = models.OneToOneField('academias.Academia', on_delete=models.PROTECT, related_name='commercial_subscription')
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT)
    pending_plan_version = models.ForeignKey(PlanVersion, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name='pending_subscriptions')
    state = models.CharField(max_length=16, choices=State.choices, default=State.TRIAL)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    trial_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=20, default='MANUAL')
    provider_subscription_id = models.CharField(max_length=150, blank=True)
    provider_state = models.CharField(max_length=40, blank=True)
    provider_customer_id = models.CharField(max_length=150, blank=True)
    payment_method_ref = models.CharField(max_length=150, blank=True)
    last_paid_period_end = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if self.period_end <= self.period_start:
            raise ValidationError('El fin del período debe ser posterior al inicio.')


class EventFeeRate(ImmutableModel):
    class Scope(models.TextChoices):
        GLOBAL = 'GLOBAL', 'Global'
        PLAN = 'PLAN', 'Plan'
        TENANT = 'TENANT', 'Academia'
        EVENT = 'EVENT', 'Evento'

    scope = models.CharField(max_length=10, choices=Scope.choices)
    academia = models.ForeignKey('academias.Academia', null=True, blank=True, on_delete=models.PROTECT)
    evento = models.ForeignKey('eventos.Evento', null=True, blank=True, on_delete=models.PROTECT)
    plan_version = models.ForeignKey(PlanVersion, null=True, blank=True, on_delete=models.PROTECT)
    fixed_per_admission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default='COP')
    effective_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=255)

    def clean(self):
        super().clean()
        targets = (self.academia_id is not None, self.evento_id is not None, self.plan_version_id is not None)
        expected = {'GLOBAL': (False, False, False), 'PLAN': (False, False, True),
                    'TENANT': (True, False, False), 'EVENT': (False, True, False)}
        if targets != expected.get(self.scope) or self.fixed_per_admission < 0 or not 0 <= self.percentage <= 100:
            raise ValidationError('Ámbito o tarifa inválida.')


class SaaSInvoice(ScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academia = models.ForeignKey('academias.Academia', on_delete=models.PROTECT, related_name='saas_invoices')
    reference = models.CharField(max_length=80, unique=True)
    source_key = models.CharField(max_length=180, unique=True)
    subscription = models.ForeignKey(CommercialSubscription, null=True, blank=True, on_delete=models.PROTECT)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    state = models.CharField(max_length=16, choices=[(v, v) for v in ('OPEN', 'PAID', 'VOID')], default='OPEN')
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Commercial account statement; not a claim of DIAN electronic invoicing.
    tax_metadata = models.JSONField(default=dict, blank=True)

    @property
    def credited_amount(self):
        from django.db.models import Sum
        return self.saascredit_set.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    @property
    def payable_amount(self):
        # Face value and immutable lines remain intact after a credit.
        return max(Decimal('0.00'), self.amount - self.credited_amount)


class InvoiceLine(ImmutableModel):
    invoice = models.ForeignKey(SaaSInvoice, on_delete=models.PROTECT, related_name='lines')
    description = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=[(v, v) for v in ('SUBSCRIPTION', 'USAGE', 'ADJUSTMENT')])
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    snapshot = models.JSONField(default=dict)


class UsageEntry(ImmutableModel):
    academia = models.ForeignKey('academias.Academia', on_delete=models.PROTECT)
    admission = models.OneToOneField('eventos.Admission', on_delete=models.PROTECT, related_name='usage')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    billable = models.BooleanField(default=False)
    reason = models.CharField(max_length=40)
    currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate = models.ForeignKey(EventFeeRate, null=True, blank=True, on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)


class UsageAllocation(ImmutableModel):
    usage = models.OneToOneField(UsageEntry, on_delete=models.PROTECT, related_name='allocation')
    invoice_line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT)


class PaymentAttempt(ScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(SaaSInvoice, on_delete=models.PROTECT, related_name='attempts')
    sequence = models.PositiveIntegerField(default=1)
    state = models.CharField(max_length=16, default='CREATED', choices=[(v, v) for v in
        ('CREATED', 'SUBMITTING', 'PENDING', 'UNKNOWN', 'SUCCEEDED', 'FAILED')])
    provider_reference = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    failure_code = models.CharField(max_length=80, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['invoice', 'sequence'], name='invoice_attempt_sequence_unique')]


class SaaSPayment(ImmutableModel):
    invoice = models.OneToOneField(SaaSInvoice, on_delete=models.PROTECT, related_name='payment')
    provider_reference = models.CharField(max_length=150, unique=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    received_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=20, default='MANUAL')


class SaaSCredit(ImmutableModel):
    academia = models.ForeignKey('academias.Academia', on_delete=models.PROTECT)
    invoice = models.ForeignKey(SaaSInvoice, null=True, blank=True, on_delete=models.PROTECT)
    usage = models.OneToOneField(UsageEntry, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    reason = models.CharField(max_length=255)
    reference = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(default=timezone.now)


class SaaSRefund(ImmutableModel):
    payment = models.ForeignKey(SaaSPayment, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    provider_reference = models.CharField(max_length=150, unique=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)


class ProviderEvent(ImmutableModel):
    fingerprint = models.CharField(max_length=64, unique=True)
    reference = models.CharField(max_length=150, db_index=True)
    payload = models.JSONField(default=dict)  # allowlisted monetary fields only
    received_at = models.DateTimeField(default=timezone.now)


class ProviderEventResult(models.Model):
    event = models.OneToOneField(ProviderEvent, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, default='RECEIVED')
    processed_at = models.DateTimeField(null=True)
    reason = models.CharField(max_length=80, blank=True)


class PaymentMandate(ScopedModel):
    academia = models.OneToOneField('academias.Academia', on_delete=models.PROTECT)
    customer_id = models.CharField(max_length=150)
    encrypted_token = models.TextField()
    document_type = models.CharField(max_length=10)
    document_number = models.CharField(max_length=50)
    payer_name = models.CharField(max_length=150)
    email = models.EmailField()
    consent_ip = models.GenericIPAddressField()
    consent_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)


class OnboardingRequest(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    email = models.EmailField()
    academy_name = models.CharField(max_length=150)
    requested_slug = models.SlugField(max_length=100)
    workspace_type = models.CharField(max_length=20, default='ACADEMY')
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
