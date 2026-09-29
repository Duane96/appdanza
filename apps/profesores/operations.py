from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from apps.saas_core.audit import record
from .models import Profesor, OrdenPagoMensual


@transaction.atomic
def mark_session(tenant, actor, session_id, confirm_payment=False):
    from apps.calendario.models import SesionClase
    from apps.finanzas.models import Gasto
    authorize(actor, tenant, 'tenant.admin')
    lock_tenant(tenant)
    session = SesionClase.objects.select_related('clase', 'profesor_asignado__usuario',
        'profesor_reemplazo__usuario').filter(pk=session_id, clase__academia=tenant).first()
    if session is None or session.estado == 'CANCELADA' or session.profe_a_pagar is None:
        raise ValidationError('La sesión no está disponible para registrar una clase dictada.')
    teacher = session.profe_a_pagar
    if session.estado == 'DICTADA' and (teacher.tipo_pago == 'MENSUAL' or session.pagada_al_profesor or not confirm_payment):
        return session
    session.estado = 'DICTADA'
    if teacher.tipo_pago == 'POR_CLASE' and confirm_payment and not session.gasto_individual_id:
        session.gasto_individual = Gasto.objects.create(academia=tenant, categoria='NOMINA',
            concepto=f'Pago clase / sesión {session.pk}', monto=session.tarifa_a_pagar,
            proveedor_nit=teacher.documento_identidad, proveedor_nombre=teacher.usuario.get_full_name(),
            es_deducible=True, fecha=timezone.localdate())
        session.pagada_al_profesor = True
    # Monthly sessions are gathered by prepare(), never appended to an approved
    # or paid statement. Its existing immutable approval boundary is preserved.
    session.save()
    record(tenant, actor, 'payroll.session.recorded', session.pk,
        after={'state': session.estado, 'paid': session.pagada_al_profesor})
    return session


@transaction.atomic
def prepare(tenant, actor):
    from apps.calendario.models import SesionClase
    authorize(actor, tenant, 'teacher.self')
    lock_tenant(tenant)
    teacher = Profesor.unfiltered_objects.filter(academia=tenant, usuario=actor, activo=True, tipo_pago='MENSUAL').first()
    if teacher is None:
        raise ValidationError('No tienes una cuenta mensual de profesor en esta academia.')
    drafts = OrdenPagoMensual.unfiltered_objects.filter(academia=tenant, profesor=teacher, estado='GENERADA')
    if drafts.count() > 1:
        raise ValidationError('Hay varias cuentas abiertas; administración debe revisarlas antes de consolidar.')
    sessions = SesionClase.objects.filter(clase__academia=tenant, estado='DICTADA', pagada_al_profesor=False).filter(
        Q(profesor_asignado=teacher, profesor_reemplazo=None) | Q(profesor_reemplazo=teacher)).filter(
        Q(orden_pago_mensual=None) | Q(orden_pago_mensual__estado='GENERADA', orden_pago_mensual__profesor=teacher))
    items = list(sessions.select_related('clase', 'profesor_asignado', 'profesor_reemplazo'))
    if not items:
        raise ValidationError('No hay clases nuevas para preparar una cuenta.')
    order = drafts.first() or OrdenPagoMensual(academia=tenant, profesor=teacher, mes_periodo=timezone.localdate().replace(day=1))
    order.cantidad_clases = len(items)
    order.monto_total = sum((Decimal(str(s.tarifa_a_pagar)) for s in items), Decimal('0'))
    order.save()
    sessions.update(orden_pago_mensual=order)
    record(tenant, actor, 'payroll.order.prepared', order.pk, after={'amount': order.monto_total})
    return order


@transaction.atomic
def decide(tenant, actor, pk, action, observation=''):
    authorize(actor, tenant, 'teacher.self')
    lock_tenant(tenant)
    order = OrdenPagoMensual.unfiltered_objects.filter(academia=tenant, profesor__usuario=actor, pk=pk).first()
    state = {'APROBAR': 'APROBADA_PROFE', 'REVISAR': 'REVISAR'}.get(action)
    if not order or not state:
        raise ValidationError('Cuenta o acción no disponible.')
    if order.estado == state:
        return order
    if order.estado not in ('GENERADA', 'REVISAR'):
        raise ValidationError('Esta cuenta ya fue enviada o pagada.')
    before = order.estado
    order.estado, order.comentarios_profe = state, observation[:2000]
    order.save()
    record(tenant, actor, 'payroll.order.reviewed', order.pk, before={'state': before}, after={'state': state})
    return order


@transaction.atomic
def pay(tenant, actor, pk):
    from apps.calendario.models import SesionClase
    from apps.finanzas.models import Gasto
    authorize(actor, tenant, 'tenant.admin')
    lock_tenant(tenant)
    order = OrdenPagoMensual.unfiltered_objects.select_related('profesor__usuario').filter(academia=tenant, pk=pk).first()
    if order and order.estado == 'PAGADA':
        return order
    if not order or order.estado != 'APROBADA_PROFE':
        raise ValidationError('La cuenta no está aprobada para pago.')
    expense = Gasto.objects.create(academia=tenant, categoria='NOMINA', concepto=f'Pago de nómina / cuenta {order.pk}',
        monto=order.monto_total, proveedor_nit=order.profesor.documento_identidad,
        proveedor_nombre=order.profesor.usuario.get_full_name(), es_deducible=True, fecha=timezone.localdate())
    order.gasto_asociado, order.estado = expense, 'PAGADA'
    order.save()
    SesionClase.objects.filter(orden_pago_mensual=order, clase__academia=tenant).update(pagada_al_profesor=True)
    record(tenant, actor, 'payroll.order.paid', order.pk, after={'amount': order.monto_total})
    return order
