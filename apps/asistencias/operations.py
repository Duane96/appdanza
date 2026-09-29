from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
from apps.calendario.models import ReservaEstudiante
from apps.saas_core.audit import record
from .models import Asistencia


@transaction.atomic
def mark(tenant, actor, *, student_id=None, token=None, mode='QR'):
    authorize(actor, tenant, 'tenant.admin')
    lock_tenant(tenant)
    students = Estudiante.unfiltered_objects.filter(academia=tenant)
    student = students.filter(pk=student_id).first() if student_id else students.filter(token_asistencia=token).first() if token else None
    if student is None:
        raise ValidationError('Estudiante no encontrado en esta academia.')
    now = timezone.now()
    if Asistencia.unfiltered_objects.filter(academia=tenant, estudiante=student,
            fecha_hora__gte=now-timedelta(minutes=1)).exists():
        return student, None, 'La asistencia ya se registró hace un momento.'
    from apps.academias.student_identity import user_for_student
    student_user = user_for_student(student)
    reservations = ReservaEstudiante.unfiltered_objects.filter(academia=tenant, estudiante=student_user,
        active=True, sesion__estado__in=['PROGRAMADA', 'DICTADA'],
        sesion__fecha_hora_inicio__lte=now+timedelta(minutes=30), sesion__fecha_hora_fin__gte=now)
    if reservations.count() > 1:
        raise ValidationError('Hay varias reservas coincidentes; revisa la sesión antes de marcar.')
    reserved = reservations.first()
    remaining = None
    if reserved:
        if reserved.asistio:
            return student, None, 'La asistencia a esta sesión ya fue registrada.'
        reserved.asistio = True
        reserved.save(update_fields=['asistio'])
    else:
        today = timezone.localdate()
        enrollment = InscripcionPlan.unfiltered_objects.filter(academia=tenant, estudiante=student,
            cancelled_at=None, fecha_inicio__lte=today, fecha_fin__gte=today, clases_restantes__gt=0).order_by('fecha_fin', 'pk').first()
        if enrollment is None:
            raise ValidationError('El estudiante no tiene clases disponibles en un plan vigente.')
        if not InscripcionPlan.unfiltered_objects.filter(pk=enrollment.pk, clases_restantes__gt=0).update(
                clases_restantes=F('clases_restantes')-1):
            raise ValidationError('El plan ya no tiene clases disponibles.')
        remaining = enrollment.clases_restantes-1
    attendance = Asistencia.unfiltered_objects.create(academia=tenant, estudiante=student, tipo_marcado=mode, registrado_por=actor)
    record(tenant, actor, 'class.attendance.recorded', attendance.pk)
    return student, remaining, 'Asistencia registrada; no se descuenta otra clase si ya tenías reserva.'
