from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from apps.planes_estudiantes.models import InscripcionPlan
from apps.saas_core.audit import record
from .models import ReciboIngreso, Gasto


@transaction.atomic
def annul(tenant, actor, kind, pk, reason):
    authorize(actor, tenant, 'tenant.admin')
    if kind not in ('ingreso', 'gasto') or not reason.strip():
        raise ValidationError('Indica un tipo de comprobante y un motivo válido.')
    lock_tenant(tenant)
    model = ReciboIngreso if kind == 'ingreso' else Gasto
    item = model.objects.filter(academia=tenant, pk=pk).first()
    if not item:
        raise ValidationError('Comprobante no encontrado.')
    if item.estado == 'ANULADO':
        return item
    item.estado, item.motivo_anulacion, item.anulado_por = 'ANULADO', reason, actor
    item.save()
    if kind == 'ingreso' and item.inscripcion_id:
        enrollment = item.inscripcion
        InscripcionPlan.unfiltered_objects.filter(pk=enrollment.pk, academia=tenant).update(cancelled_at=timezone.now())
        # Preserve enrollment, balance, receipt link and class history.
        if not InscripcionPlan.unfiltered_objects.filter(estudiante=enrollment.estudiante, academia=tenant,
            cancelled_at=None, fecha_fin__gte=timezone.localdate(), clases_restantes__gt=0).exists():
            enrollment.estudiante.estado = 'INACTIVO'
            enrollment.estudiante.save(update_fields=['estado'])
    record(tenant, actor, f'finance.{kind}.annulled', pk, before={'state': 'ACTIVO'},
           after={'state': 'ANULADO'}, reason=reason)
    return item
