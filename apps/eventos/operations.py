"""Authoritative pricing and explicit, transactional payment/access operations."""
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.saas_core.audit import record
from apps.saas_core.jobs import enqueue
from .models import (Evento, TipoPase, CodigoDescuento, ReciboEvento, EntradaQR,
                     Admission, CheckIn, EventRefund)

ZERO = Decimal('0.00')
MAX_QUANTITY = 25


def _write_lock(event_id):
    # Acquire SQLite's writer reservation before reading a mutable aggregate;
    # PostgreSQL locks the event row. This does not change any legacy fingerprint.
    if not Evento.unfiltered_objects.filter(pk=event_id).update(updated_at=F('updated_at')):
        raise ValidationError('Evento no disponible.')


def quote(event, pass_input, quantity, coupon_text='', *, door=False):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValidationError('Cantidad inválida.')
    if not 1 <= quantity <= MAX_QUANTITY:
        raise ValidationError(f'La cantidad debe estar entre 1 y {MAX_QUANTITY}.')
    allowed_states = {'REGISTRO_ONLINE', 'REGISTRO_PUERTA'} if door else {'REGISTRO_ONLINE'}
    if event.estado not in allowed_states:
        raise ValidationError('El evento no admite nuevas ventas en este estado.')
    phase = event.fases_preventa.filter(fecha_limite__gte=timezone.now()).order_by('fecha_limite').first() if event.tiene_fases_fechas else None
    if phase is None:
        phase = event.fases_preventa.order_by('-fecha_limite').first()
    selected_pass = None
    if str(pass_input).startswith('PASE_'):
        pass_id = str(pass_input)[5:]
        if not pass_id.isdigit():
            raise ValidationError('Pase inválido.')
        selected_pass = TipoPase.objects.filter(pk=pass_id, evento=event, activo=True).first()
        if selected_pass is None:
            raise ValidationError('El pase no pertenece a este evento o no está activo.')
        price = selected_pass.precio
        if phase:
            pivot = phase.precios_pases.filter(pase=selected_pass, pase__evento=event).first()
            if pivot:
                price = pivot.precio
        accesses = selected_pass.accesos_permitidos
        access_units = selected_pass.qrs_por_pase
        commercial_units = selected_pass.admissions_per_unit
    else:
        if event.pases_personalizados.exists() or pass_input not in ('FULL', 'DIA'):
            raise ValidationError('Selecciona un pase activo del evento.')
        # Read compatibility for events which genuinely have no pass catalog.
        price = event.precio_por_dia if pass_input == 'DIA' else (event.precio_puerta if door else event.precio_preventa)
        accesses = 1 if pass_input == 'DIA' else max(1, event.cantidad_dias)
        access_units, commercial_units = 1, None
    if not 1 <= access_units <= 10 or not 1 <= accesses <= 366:
        raise ValidationError('La configuración del pase requiere revisión administrativa.')
    if commercial_units is not None and not 1 <= commercial_units <= 10:
        raise ValidationError('Las admisiones comerciales por pase deben estar entre 1 y 10.')
    price = Decimal(str(price or 0))
    base_price = price
    coupon = None
    if coupon_text:
        coupon = CodigoDescuento.objects.filter(evento=event, nombre_codigo__iexact=coupon_text.strip(), activo=True).first()
        if not coupon or not coupon.es_valido:
            raise ValidationError('El cupón no es válido, venció o agotó sus cupos.')
        if coupon.pase_aplicable_id and (not selected_pass or coupon.pase_aplicable_id != selected_pass.pk):
            raise ValidationError('El cupón no aplica al pase seleccionado.')
        price = coupon.precio_especial if accesses > 1 or coupon.precio_especial_dia is None else coupon.precio_especial_dia
    if price < ZERO or base_price < ZERO:
        raise ValidationError('El precio requiere revisión administrativa.')
    return {'pass': selected_pass, 'phase': phase, 'coupon': coupon,
            'snapshot': {'quantity': quantity, 'unit_price': str(price), 'base_unit_price': str(base_price),
                'total': str((quantity * price).quantize(Decimal('0.01'))), 'currency': event.academia.divisa,
                'access_units': quantity * (commercial_units if commercial_units is not None else access_units), 'access_limit': accesses,
                'commercial_units': quantity * commercial_units if commercial_units is not None else None,
                'pass_id': selected_pass.pk if selected_pass else None, 'phase_id': phase.pk if phase else None,
                'coupon_id': coupon.pk if coupon else None,
                'pricing_source': 'CATALOG' if selected_pass else 'LEGACY_CATALOG'}}


@transaction.atomic
def register(event, values, *, key, pass_input, coupon_text='', actor=None, door=False):
    if door:
        authorize(actor, event.academia, 'events.sell', event)
    _write_lock(event.pk)
    event.refresh_from_db()
    try:
        key = uuid.UUID(str(key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('La solicitud necesita una referencia válida. Actualiza la página.')
    existing = ReciboEvento.objects.filter(registration_key=key).first()
    if existing:
        if existing.evento_id != event.pk:
            raise ValidationError('Referencia de registro inválida.')
        return existing
    priced = quote(event, pass_input, values.get('cantidad_entradas'), coupon_text, door=door)
    snapshot, coupon = priced['snapshot'], priced['coupon']
    if coupon:
        consumed = CodigoDescuento.objects.filter(pk=coupon.pk, activo=True,
            fecha_caducidad__gte=timezone.now(), usos_actuales__lt=F('limite_usos')).update(usos_actuales=F('usos_actuales') + 1)
        if not consumed:
            raise ValidationError('El cupón agotó sus cupos. Revisa el total antes de pagar.')
    receipt = ReciboEvento.objects.create(evento=event, registration_key=key,
        comprador_nombre=values.get('comprador_nombre', ''), comprador_correo=values.get('comprador_correo') or None,
        comprador_telefono=values.get('comprador_telefono', ''), cantidad_entradas=snapshot['quantity'],
        comprobante_pago=values.get('comprobante_pago'), precio_unitario_aplicado=Decimal(snapshot['unit_price']),
        monto_total=Decimal(snapshot['total']), price_snapshot=snapshot, tipo_pase=priced['pass'],
        fase_preventa=priced['phase'], codigo_descuento_usado=coupon, revisado_por_admin=False,
        payment_status='PENDING', origen='PUERTA' if door else 'ONLINE',
        medio_pago=values.get('medio_pago', 'TRANSFERENCIA') if door else 'TRANSFERENCIA')
    record(event.academia, actor, 'event.registration.created', receipt.pk,
           after={'payment_status': 'PENDING', 'total': receipt.monto_total, 'quantity': receipt.cantidad_entradas})
    return receipt


@transaction.atomic
def confirm(receipt, actor, reason):
    authorize(actor, receipt.evento.academia, 'events.sell', receipt.evento)
    if not reason.strip():
        raise ValidationError('Indica la evidencia o motivo de aprobación.')
    _write_lock(receipt.evento_id)
    receipt.refresh_from_db()
    if receipt.payment_status == 'CONFIRMED':
        return receipt
    if receipt.payment_status not in ('PENDING', 'REVIEW') or receipt.anulado:
        raise ValidationError('Esta operación no puede confirmarse desde su estado actual.')
    snapshot = receipt.price_snapshot
    if not snapshot or not snapshot.get('access_units'):
        raise ValidationError('El registro requiere una cotización válida antes de confirmar.')
    ReciboEvento.objects.filter(pk=receipt.pk).update(payment_status='CONFIRMED', revisado_por_admin=True,
                                                    confirmed_at=timezone.now())
    prior_status = receipt.payment_status
    receipt.refresh_from_db()
    commercial = snapshot.get('commercial_units')
    # Operational legacy QR multipliers do not define a SaaS commercial unit.
    for ordinal in range(1, snapshot['access_units'] + 1):
        admission, _ = Admission.objects.get_or_create(receipt=receipt, ordinal=ordinal,
            defaults={'access_limit': snapshot['access_limit'],
                      'commercial_unit': commercial is not None and ordinal <= commercial})
        EntradaQR.objects.get_or_create(admission=admission, defaults={'recibo': receipt,
                                       'asistencias_permitidas': admission.access_limit})
        from apps.saas_core.billing import meter_admission
        meter_admission(admission)
    record(receipt.evento.academia, actor, 'event.payment.confirmed', receipt.pk,
           before={'payment_status': prior_status}, after={'payment_status': 'CONFIRMED'}, reason=reason)
    receipt.refresh_from_db()
    return receipt


@transaction.atomic
def cancel(receipt, actor, reason):
    authorize(actor, receipt.evento.academia, 'events.manage', receipt.evento)
    if not reason.strip():
        raise ValidationError('Indica el motivo de anulación.')
    _write_lock(receipt.evento_id)
    receipt.refresh_from_db()
    if receipt.anulado:
        return receipt
    if receipt.payment_status == 'REFUNDED':
        raise ValidationError('La devolución ya fue registrada.')
    before = receipt.payment_status
    ReciboEvento.objects.filter(pk=receipt.pk).update(anulado=True, payment_status='CANCELLED')
    receipt.boletas_qr.filter(revoked_at=None).update(revoked_at=timezone.now())
    if before in ('PENDING', 'REVIEW') and receipt.codigo_descuento_usado_id:
        CodigoDescuento.objects.filter(pk=receipt.codigo_descuento_usado_id, usos_actuales__gt=0).update(usos_actuales=F('usos_actuales') - 1)
    record(receipt.evento.academia, actor, 'event.registration.cancelled', receipt.pk,
           before={'payment_status': before}, after={'payment_status': 'CANCELLED', 'anulado': True}, reason=reason)
    receipt.refresh_from_db()
    return receipt


@transaction.atomic
def record_refund(receipt, actor, *, amount, reference, reason):
    authorize(actor, receipt.evento.academia, 'events.manage', receipt.evento)
    _write_lock(receipt.evento_id)
    receipt.refresh_from_db()
    existing = EventRefund.objects.filter(reference=reference).first()
    if existing:
        if existing.receipt_id != receipt.pk or existing.amount != Decimal(str(amount)):
            raise ValidationError('La referencia ya pertenece a otra devolución.')
        return existing
    if receipt.payment_status != 'CONFIRMED' or not reference.strip() or not reason.strip():
        raise ValidationError('Se requiere un pago confirmado y evidencia de devolución real.')
    amount = Decimal(str(amount))
    if amount != receipt.monto_total or amount <= ZERO:
        raise ValidationError('Este flujo registra únicamente devoluciones totales comprobadas.')
    refund = EventRefund.objects.create(receipt=receipt, actor=actor, amount=amount, reference=reference, reason=reason)
    receipt.boletas_qr.filter(revoked_at=None).update(revoked_at=timezone.now())
    ReciboEvento.objects.filter(pk=receipt.pk).update(payment_status='REFUNDED', anulado=True)
    from apps.saas_core.billing import credit_refunded_admissions
    credit_refunded_admissions(receipt, refund, actor)
    record(receipt.evento.academia, actor, 'event.payment.refund_recorded', receipt.pk,
           before={'payment_status': 'CONFIRMED'}, after={'payment_status': 'REFUNDED', 'amount': amount}, reason=reason)
    return refund


@transaction.atomic
def check_in(event, actor, code, *, request_key=None):
    authorize(actor, event.academia, 'events.checkin', event)
    _write_lock(event.pk)
    try:
        code = uuid.UUID(str(code))
        request_key = uuid.UUID(str(request_key)) if request_key else uuid.uuid4()
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Código de entrada inválido.')
    previous = CheckIn.objects.filter(request_key=request_key, credential__recibo__evento=event).first()
    if previous:
        if previous.credential_code != code:
            raise ValidationError('La referencia del intento no corresponde a esa entrada.')
        return previous
    ticket = EntradaQR.objects.select_related('recibo').filter(codigo_unico=code, recibo__evento=event).first()
    if ticket is None:
        raise ValidationError('Entrada no válida para este evento.')
    today = timezone.localdate()
    result = 'SUCCESS'
    if ticket.revoked_at or ticket.recibo.anulado or ticket.recibo.payment_status not in ('LEGACY', 'CONFIRMED'):
        result = 'REVOKED'
    elif ticket.fecha_ultimo_ingreso and timezone.localdate(ticket.fecha_ultimo_ingreso) == today:
        result = 'ALREADY_USED_TODAY'
    elif ticket.asistencias_consumidas >= ticket.asistencias_permitidas:
        result = 'EXHAUSTED'
    if result == 'SUCCESS':
        changed = EntradaQR.objects.filter(pk=ticket.pk, revoked_at=None,
            asistencias_consumidas__lt=F('asistencias_permitidas')).update(
            asistencias_consumidas=F('asistencias_consumidas') + 1, fecha_ultimo_ingreso=timezone.now())
        if not changed:
            result = 'EXHAUSTED'
    return CheckIn.objects.create(credential=ticket, credential_code=code, day=today, actor=actor,
                                  result=result, request_key=request_key)


@transaction.atomic
def reissue(ticket, actor, reason):
    authorize(actor, ticket.recibo.evento.academia, 'events.manage', ticket.recibo.evento)
    _write_lock(ticket.recibo.evento_id)
    ticket.refresh_from_db()
    if not reason.strip() or ticket.revoked_at or ticket.recibo.anulado:
        raise ValidationError('No se puede reemitir esta credencial.')
    ticket.codigo_unico = uuid.uuid4()
    ticket.imagen_qr = ''
    ticket.save(update_fields=['codigo_unico', 'imagen_qr'])
    enqueue('EVENT_QR', {'ticket_id': ticket.pk}, tenant=ticket.recibo.evento.academia,
            key=f'qr:{ticket.pk}:{ticket.codigo_unico}')
    record(ticket.recibo.evento.academia, actor, 'event.credential.reissued', ticket.pk, reason=reason)
    return ticket
