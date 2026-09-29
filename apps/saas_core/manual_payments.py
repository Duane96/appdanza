from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from .models import ReportePagoSaaS
from .billing import settle
from .audit import record


@transaction.atomic
def approve_proof(pk, actor, bank_reference):
    authorize(actor, None, 'platform.manage')
    report = ReportePagoSaaS.objects.select_related('academia', 'invoice').get(pk=pk)
    lock_tenant(report.academia)
    report.refresh_from_db()
    if report.estado == 'APROBADO':
        return report
    if report.estado != 'PENDIENTE' or not report.invoice_id or not bank_reference.strip():
        raise ValidationError('Se requiere una cuenta de cobro y una referencia bancaria verificada.')
    settle(report.invoice, reference='MANUAL:'+bank_reference.strip(), amount=report.invoice.payable_amount,
           currency=report.invoice.currency, source='MANUAL', actor=actor)
    report.estado = 'APROBADO'
    report.save(update_fields=['estado'])
    record(report.academia, actor, 'billing.proof.approved', report.pk)
    return report
