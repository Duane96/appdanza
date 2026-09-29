from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from apps.academias.private_media import validate_private_upload
from .models import (BillingAccount, CommercialSubscription, PlanVersion, SaaSInvoice, SaaSPayment,
    ReportePagoSaaS, ConfigPagoGlobalSaaS, UsageEntry, PaymentAttempt, DurableJob, SaaSCredit, SaaSRefund)
from .policy import BillingPolicy, EntitlementService
from .billing import cancel_subscription, add_months, invoice_subscription
from .audit import record
from .epayco import receive_webhook, ProviderError


@require_GET
def portal(request, slug_academia):
    tenant = request.tenant
    authorize(request.user, tenant, 'billing.manage')
    policy = BillingPolicy(tenant)
    entitlements = EntitlementService(tenant)
    usage = {name: {'used': entitlements.usage(name), 'limit': policy.features.get(name)}
             for name in ('max_students', 'max_teachers', 'max_events')}
    from .epayco import config
    try:
        configured = bool(config()) and bool(settings.APPDANZA_TOKEN_ENCRYPTION_KEY)
    except ProviderError:
        configured = False
    return render(request, 'saas_core/billing_portal.html', {'academia': tenant,
        'policy': policy, 'usage': usage, 'features': policy.features,
        'epayco_ready': configured and policy.can_invoice,
        'epayco_public_key': settings.APPDANZA_EPAYCO_PUBLIC_KEY if configured else '',
        'invoices': SaaSInvoice.objects.filter(academia=tenant).order_by('-created_at')[:50],
        'payments': SaaSPayment.objects.filter(invoice__academia=tenant).select_related('invoice').order_by('-received_at')[:50],
        'credits': SaaSCredit.objects.filter(academia=tenant).order_by('-created_at')[:50],
        'refunds': SaaSRefund.objects.filter(payment__invoice__academia=tenant).select_related('payment').order_by('-created_at')[:50],
        'versions': PlanVersion.objects.filter(published=True).select_related('plan'),
        'payment_instructions': ConfigPagoGlobalSaaS.objects.first()})


@require_POST
def mandate(request, slug_academia):
    from .mandates import register_mandate, revoke_mandate
    allowed = {'csrfmiddlewaretoken', 'token', 'document_type', 'document_number', 'consent', 'action'}
    if set(request.POST) - allowed:
        return JsonResponse({'error': 'unexpected_fields'}, status=400)
    try:
        if request.POST.get('action') == 'revoke':
            revoke_mandate(request.tenant, request.user)
        else:
            register_mandate(request.tenant, request.user, token=request.POST.get('token', ''),
                document_type=request.POST.get('document_type', ''), document_number=request.POST.get('document_number', ''),
                consent=request.POST.get('consent') == 'yes', ip=request.META.get('REMOTE_ADDR', '127.0.0.1'))
        messages.success(request, 'Autorización de pago actualizada.')
    except (ValidationError, ProviderError):
        messages.error(request, 'No se pudo actualizar el medio de pago. Revisa los datos o contacta con soporte.')
    return redirect('saas_core:billing_portal', slug_academia=slug_academia)


@require_POST
def select_plan(request, slug_academia):
    tenant = request.tenant
    authorize(request.user, tenant, 'billing.manage')
    try:
        if request.POST.get('accept_terms') != 'yes':
            raise ValidationError('Confirma el importe y las condiciones del plan seleccionado.')
        with transaction.atomic():
            lock_tenant(tenant)
            policy = BillingPolicy(tenant)
            if policy.account and policy.account.mode == 'INTERNAL':
                raise ValidationError('El tenant interno permanece exento de cobros.')
            version = get_object_or_404(PlanVersion, pk=request.POST.get('version'), published=True)
            now = timezone.now()
            if policy.subscription and policy.subscription.state != 'CANCELLED':
                policy.subscription.pending_plan_version = version
                policy.subscription.save(update_fields=['pending_plan_version'])
                messages.success(request, 'Cambio solicitado para el próximo período. El acceso actual se conserva.')
            else:
                account, _ = BillingAccount.objects.get_or_create(academia=tenant)
                account.mode, account.automatic_charges_authorized = 'PAID', False
                account.billing_email = request.user.email
                account.save()
                subscription, _ = CommercialSubscription.objects.update_or_create(academia=tenant, defaults={
                    'plan_version': version, 'state': 'ACTIVE', 'period_start': now,
                    'period_end': add_months(now, version.interval_months), 'accepted_at': now,
                    'provider': 'MANUAL', 'cancel_at_period_end': False, 'cancelled_at': None})
                invoice_subscription(tenant, subscription.period_start, subscription.period_end)
                messages.success(request, 'Plan contratado. Revisa la cuenta de cobro y los datos de pago.')
            record(tenant, request.user, 'billing.plan.selected', version.pk, after={'plan_version_id': version.pk})
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('saas_core:billing_portal', slug_academia=tenant.slug)


@require_POST
def cancel(request, slug_academia):
    try:
        cancel_subscription(request.tenant, request.user)
        messages.success(request, 'Cancelación solicitada para el final del período. Tus datos se conservan.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('saas_core:billing_portal', slug_academia=slug_academia)


@require_POST
def upload_proof(request, slug_academia, invoice_id):
    authorize(request.user, request.tenant, 'billing.manage')
    invoice = get_object_or_404(SaaSInvoice, pk=invoice_id, academia=request.tenant, state='OPEN')
    try:
        upload = request.FILES.get('comprobante')
        if not upload:
            raise ValidationError('Adjunta el comprobante de pago.')
        validate_private_upload(upload)
        with transaction.atomic():
            lock_tenant(request.tenant)
            if not ReportePagoSaaS.objects.filter(invoice=invoice, estado='PENDIENTE').exists():
                report = ReportePagoSaaS.objects.create(academia=request.tenant, invoice=invoice,
                    plan=invoice.subscription.plan_version.plan if invoice.subscription else None, comprobante=upload)
                record(request.tenant, request.user, 'billing.proof.uploaded', report.pk)
        messages.success(request, 'Comprobante recibido para revisión. Aún no se considera un pago confirmado.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('saas_core:billing_portal', slug_academia=slug_academia)


@csrf_exempt  # Provider signature and independent server lookup replace browser CSRF.
@require_POST
def epayco_confirmation(request):
    if len(request.body) > 32*1024:
        return JsonResponse({'error': 'payload_too_large'}, status=413)
    try:
        receive_webhook(request.POST)
    except ValidationError:
        return JsonResponse({'error': 'invalid_confirmation'}, status=400)
    except ProviderError:
        return JsonResponse({'error': 'provider_not_configured'}, status=503)
    return JsonResponse({'received': True})


@require_GET
def master(request):
    authorize(request.user, None, 'platform.manage')
    subscriptions = CommercialSubscription.objects.select_related('academia__billing_account', 'plan_version')
    mrr = {}
    for sub in subscriptions.filter(state='ACTIVE', academia__billing_account__mode='PAID', accepted_at__isnull=False):
        version = sub.plan_version
        mrr[version.currency] = mrr.get(version.currency, Decimal('0')) + version.amount / version.interval_months
    outstanding = {r['currency']: r['total'] for r in SaaSInvoice.objects.filter(state='OPEN').values('currency').annotate(total=Sum('amount'))}
    for credit in SaaSCredit.objects.filter(invoice__state='OPEN').values('currency').annotate(total=Sum('amount')):
        outstanding[credit['currency']] -= credit['total']
    from apps.eventos.models import Evento, ReciboEvento
    from apps.academias.models import Academia
    accounts = list(BillingAccount.objects.select_related('academia').order_by('academia__nombre'))
    contracts = {sub.academia_id: sub for sub in subscriptions}
    event_counts = dict(Evento.unfiltered_objects.values('academia_id').annotate(n=Count('pk')).values_list('academia_id', 'n'))
    confirmed = dict(ReciboEvento.objects.filter(revisado_por_admin=True, anulado=False).values('evento__academia_id').annotate(n=Count('pk')).values_list('evento__academia_id', 'n'))
    usage_counts = dict(UsageEntry.objects.filter(billable=True).values('academia_id').annotate(n=Count('pk')).values_list('academia_id', 'n'))
    for account in accounts:
        account.contract = contracts.get(account.academia_id)
        account.event_count = event_counts.get(account.academia_id, 0)
        account.confirmed_count = confirmed.get(account.academia_id, 0)
        account.usage_count = usage_counts.get(account.academia_id, 0)
    return render(request, 'saas_core/billing_master.html', {
        'accounts': accounts,
        'tenant_total': Academia.unfiltered_objects.count(),
        'policy_counts': BillingAccount.objects.values('mode').annotate(total=Count('pk')).order_by('mode'),
        'subscriptions': subscriptions, 'mrr': mrr,
        'open_invoices': [{'currency': currency, 'total': total} for currency, total in outstanding.items()],
        'attempts': PaymentAttempt.objects.select_related('invoice__academia').exclude(state='SUCCEEDED').order_by('-created_at')[:30],
        'jobs_failed': DurableJob.objects.filter(state='FAILED').count(),
        'proofs': ReportePagoSaaS.objects.filter(estado='PENDIENTE').select_related('academia', 'invoice')})


from django.utils import timezone
