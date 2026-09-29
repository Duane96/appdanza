"""Read-only academy totals. Independent aggregates avoid receipt/expense joins."""
from decimal import Decimal
from django.db.models import Sum, Count
from apps.eventos.models import Evento, ReciboEvento, GastoEvento

ZERO = Decimal('0.00')


def event_totals(academia_id):
    receipts = ReciboEvento.objects.filter(evento__academia_id=academia_id, anulado=False,
                                           revisado_por_admin=True)
    income = {(r['evento_id'], r['origen']): r for r in receipts.values('evento_id', 'origen').annotate(
        total=Sum('monto_total'), count=Count('pk'))}
    expenses = {r['evento_id']: r['total'] for r in GastoEvento.objects.filter(
        evento__academia_id=academia_id).values('evento_id').annotate(total=Sum('monto'))}
    results = []
    for event in Evento.unfiltered_objects.filter(academia_id=academia_id).order_by('pk'):
        online = income.get((event.pk, 'ONLINE'), {})
        door = income.get((event.pk, 'PUERTA'), {})
        total = online.get('total', ZERO) + door.get('total', ZERO)
        expense = expenses.get(event.pk, ZERO)
        results.append({'nombre': event.nombre, 'cant_recibos': online.get('count', 0) + door.get('count', 0),
                        'ingresos_online': online.get('total', ZERO), 'ingresos_taquilla': door.get('total', ZERO),
                        'gastos': expense, 'total_ingreso': total, 'neto': total - expense})
    return results
