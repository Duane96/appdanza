from decimal import Decimal
from .models import AuditEvent

ALLOWED_FIELDS = {'state', 'status', 'estado', 'role', 'active', 'plan_id', 'plan_version_id',
    'billing_exempt', 'mode', 'ends_at', 'starts_at', 'amount', 'currency', 'total',
    'payment_status', 'revisado_por_admin', 'anulado', 'count', 'fee_policy_id',
    'accesses', 'quantity', 'source', 'reason_code', 'capabilities', 'limits', 'version',
    'academia_id', 'user_id', 'event_id', 'receipt_id', 'invoice_id', 'payment_id'}


def sanitized_snapshot(data):
    result = {}
    for key, value in (data or {}).items():
        if key in ALLOWED_FIELDS:
            result[key] = str(value) if isinstance(value, Decimal) else value
    return result


def record(tenant, actor, action, resource, *, before=None, after=None, reason='', service='', correlation_id=None):
    values = dict(academia=tenant, actor=actor if getattr(actor, 'is_authenticated', False) else None,
                  action=action, resource=str(resource), before=sanitized_snapshot(before),
                  after=sanitized_snapshot(after), reason=reason[:255], service=service)
    if correlation_id:
        values['correlation_id'] = correlation_id
    return AuditEvent.objects.create(**values)
