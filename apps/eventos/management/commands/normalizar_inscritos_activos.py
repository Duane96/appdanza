"""Restore active event admissions and resend QR credentials once.

Dry-run by default. This command never modifies finalized events, cancelled
or refunded receipts, or historical price/receipt values.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.eventos.models import Evento, ReciboEvento
from apps.eventos.operations import _ensure_credentials, _write_lock
from apps.eventos.tickets import queue_ticket_email
from apps.saas_core.audit import record
from gestoracademia.tenants import clear_current_tenant, get_current_tenant, set_current_tenant


def recover_snapshot(receipt):
    """Infer access from original passes / issued QR without inventing purchases."""
    original = list(receipt.boletas_qr.filter(revoked_at=None))
    pass_ = receipt.tipo_pase
    quantity = max(1, receipt.cantidad_entradas)
    multiplier = max(1, pass_.qrs_por_pase) if pass_ else 1
    limit = max([1, pass_.accesos_permitidos if pass_ else 1] +
                [ticket.asistencias_permitidas for ticket in original])
    return {
        'quantity': quantity, 'unit_price': str(receipt.precio_unitario_aplicado),
        'total': str(receipt.monto_total), 'currency': receipt.evento.academia.divisa,
        'access_units': max(quantity * multiplier, len(original)),
        'access_limit': limit, 'commercial_units': None,
        'pass_id': receipt.tipo_pase_id, 'phase_id': receipt.fase_preventa_id,
        'pricing_source': 'HISTORICAL_RECOVERY',
    }


@transaction.atomic
def normalize_receipt(receipt):
    """Idempotent conversion and QR repair; delivery runs after commit."""
    _write_lock(receipt.evento_id)
    receipt.refresh_from_db()
    if receipt.anulado or receipt.payment_status in ('CANCELLED', 'REFUNDED'):
        return (False, 0, False)
    if receipt.evento.estado == 'FINALIZADO':
        raise ValueError('A finalized event needs explicit owner review')

    snapshot = receipt.price_snapshot or {}
    if not snapshot.get('access_units'):
        snapshot = recover_snapshot(receipt)
        ReciboEvento.objects.filter(pk=receipt.pk).update(price_snapshot=snapshot)
        receipt.refresh_from_db()

    before = receipt.boletas_qr.filter(revoked_at=None).count()
    admissions = _ensure_credentials(receipt, snapshot)
    created = receipt.boletas_qr.filter(revoked_at=None).count() - before
    accepted = receipt.payment_status in ('PENDING', 'REVIEW') or (
        receipt.payment_status == 'LEGACY' and not receipt.revisado_por_admin
    )
    if accepted:
        old_status = receipt.payment_status
        ReciboEvento.objects.filter(pk=receipt.pk).update(
            payment_status='CONFIRMED', revisado_por_admin=True,
            confirmed_at=receipt.confirmed_at or timezone.now(),
        )
        receipt.refresh_from_db()
        if snapshot.get('commercial_units') is not None:
            from apps.saas_core.billing import meter_admission
            for admission in admissions:
                meter_admission(admission)
        record(receipt.evento.academia, None, 'event.registration.recovered', receipt.pk,
               reason='Normalización de inscritos activos autorizada por organizador',
               before={'payment_status': old_status}, after={'payment_status': 'CONFIRMED'})
    elif receipt.payment_status == 'CONFIRMED' and not receipt.revisado_por_admin:
        ReciboEvento.objects.filter(pk=receipt.pk).update(revisado_por_admin=True)
        receipt.refresh_from_db()

    # Do not resend to recent buyers who already received the normal email.
    has_email = bool(receipt.comprador_correo)
    already_queued = False
    if has_email:
        from apps.saas_core.models import DurableJob
        already_queued = DurableJob.objects.filter(
            dedupe_key=f'event-ticket-email:{receipt.pk}:CONFIRMED:first',
        ).exclude(state='FAILED').exists()
    if has_email and not already_queued and receipt.payment_status in ('CONFIRMED', 'LEGACY'):
        queue_ticket_email(receipt, 'RECOVERED', version='active-events-recovery-v1')
    return (accepted, created, has_email)


class Command(BaseCommand):
    help = 'Regulariza registros activos y envía los QR por correo (simulación por defecto).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Aplicar cambios y enviar correos')
        parser.add_argument('--event-id', type=int, help='Limitar a un evento activo por ID')

    def handle(self, *args, **options):
        events = Evento.unfiltered_objects.select_related('academia').exclude(estado='FINALIZADO')
        if options['event_id'] is not None:
            events = events.filter(pk=options['event_id'])
            if not events.exists():
                raise CommandError('No existe un evento activo con ese ID.')
        counters = {'events': 0, 'receipts': 0, 'accepted': 0, 'new_qrs': 0,
                    'emails': 0, 'without_email': 0, 'errors': 0}
        previous_tenant = get_current_tenant()
        try:
            for event in events.order_by('pk'):
                set_current_tenant(event.academia)
                receipts = list(
                    ReciboEvento.objects.filter(evento=event, anulado=False)
                    .exclude(payment_status__in=('CANCELLED', 'REFUNDED'))
                    .select_related('tipo_pase', 'evento__academia').order_by('pk')
                )
                counters['events'] += 1
                counters['receipts'] += len(receipts)
                self.stdout.write(f'Evento #{event.pk} {event.nombre}: {len(receipts)} inscritos válidos')
                if not options['apply']:
                    counters['accepted'] += sum(
                        1 for r in receipts if r.payment_status in ('PENDING', 'REVIEW') or (
                            r.payment_status == 'LEGACY' and not r.revisado_por_admin
                        )
                    )
                    counters['emails'] += sum(bool(r.comprador_correo) for r in receipts)
                    counters['without_email'] += sum(not r.comprador_correo for r in receipts)
                    continue
                for receipt in receipts:
                    try:
                        accepted, new_qrs, has_email = normalize_receipt(receipt)
                    except Exception as exc:
                        counters['errors'] += 1
                        self.stderr.write(f'Registro #{receipt.pk}: {type(exc).__name__}')
                    else:
                        counters['accepted'] += int(accepted)
                        counters['new_qrs'] += new_qrs
                        counters['emails'] += int(has_email)
                        counters['without_email'] += int(not has_email)
        finally:
            if previous_tenant is None:
                clear_current_tenant()
            else:
                set_current_tenant(previous_tenant)
        status = 'APLICADO' if options['apply'] else 'SIMULACIÓN (sin cambios)'
        self.stdout.write(self.style.SUCCESS(f'{status}: {counters}'))
        if counters['errors']:
            raise CommandError(f'{counters["errors"]} registros requieren revisión técnica.')
