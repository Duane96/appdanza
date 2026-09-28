"""Small financial read API. No checkout callbacks and no customer data."""
import hashlib
import json
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from .models import Evento


def is_dya_tenant(tenant):
    return bool(tenant and tenant.pk == 3 and tenant.slug == 'bachatamania' and tenant.divisa == 'COP')


def payload(event):
    receipts = list(event.recibos_evento.order_by('pk').values(
        'id', 'numero_recibo', 'cantidad_entradas', 'precio_unitario_aplicado',
        'monto_total', 'medio_pago', 'origen', 'revisado_por_admin', 'fecha',
        'anulado', 'codigo_descuento_usado_id', 'tipo_pase_id', 'fase_preventa_id'))
    expenses = list(event.gastos_evento.order_by('pk').values('id', 'concepto', 'monto', 'fecha'))
    result = {
        'event': {field: getattr(event, field) for field in (
            'id', 'academia_id', 'nombre', 'slug', 'fecha', 'ubicacion', 'ciudad',
            'enlace_externo', 'estado', 'creado_en', 'updated_at', 'connect_dya_finances',
            'deuda_online_calculada', 'deuda_puerta_calculada', 'online_liquidado', 'puerta_liquidado')},
        'receipts': receipts, 'expenses': expenses,
        # The current source has annulments, not a separate refund ledger.
        # Never label an annulment as proof of money returned.
        'refunds': [], 'refund_semantics': 'annulments_in_receipts_no_refund_ledger',
        'income': {'paid_receipts_total': sum((r['monto_total'] for r in receipts
                    if r['revisado_por_admin'] and not r['anulado']), Decimal('0.00'))},
    }
    result['event'].update(tenant_slug=event.academia.slug, tenant_city=event.academia.ciudad or '',
                           currency=event.academia.divisa)
    result['fingerprint'] = hashlib.sha256(json.dumps(result, cls=DjangoJSONEncoder,
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


@require_GET
def events(request, external_id=None):
    token = settings.DYA_INTEGRATION_API_TOKEN
    supplied = request.headers.get('Authorization', '')
    if not token or not secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return JsonResponse({'error': 'unauthorized'}, status=401)
    if not settings.DEBUG and not request.is_secure():
        return JsonResponse({'error': 'https_required'}, status=403)
    with transaction.atomic():
        queryset = Evento.unfiltered_objects.filter(academia_id=3, academia__slug='bachatamania',
            academia__divisa='COP', connect_dya_finances=True).select_related('academia').prefetch_related(
            'recibos_evento', 'gastos_evento').order_by('pk')
        if external_id is not None:
            event = queryset.filter(pk=external_id).first()
            if event is None:
                return JsonResponse({'error': 'not_found'}, status=404)
            result = {'schema_version': 1, **payload(event)}
        else:
            # Whole consistent snapshot catches child edits/deletions even when
            # event.updated_at does not change. Local fingerprints skip writes.
            result = {'schema_version': 1, 'complete': True, 'events': [payload(e) for e in queryset]}
    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response
