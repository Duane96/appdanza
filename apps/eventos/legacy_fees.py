"""Read-only legacy debt. Never apply old fixed fees to new registrations."""
from decimal import Decimal
from django.db.models import Sum


def statement(event):
    from apps.saas_core.policy import BillingPolicy
    policy = BillingPolicy(event.academia)
    legacy = event.recibos_evento.filter(payment_status='LEGACY', anulado=False)
    online = legacy.filter(origen='ONLINE').aggregate(n=Sum('cantidad_entradas'))['n'] or 0
    door = legacy.filter(origen='PUERTA').aggregate(n=Sum('cantidad_entradas'))['n'] or 0
    return {'total_online': online, 'total_puerta': door,
        'deuda_online': Decimal('0') if policy.exempt or event.online_liquidado else event.deuda_online_calculada,
        'deuda_puerta': Decimal('0') if policy.exempt or event.puerta_liquidado else event.deuda_puerta_calculada,
        'es_minima_online': False, 'divisa': event.academia.divisa, 'modo_partner': policy.exempt,
        'source': 'LEGACY_FROZEN'}
