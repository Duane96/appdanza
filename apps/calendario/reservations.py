from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from apps.academias.authorization import authorize
from apps.academias.locks import lock_tenant
from apps.academias.student_identity import student_for
from apps.planes_estudiantes.models import InscripcionPlan
from apps.saas_core.audit import record
from .models import SesionClase, ReservaEstudiante


@transaction.atomic
def change_reservation(tenant, user, session_id, action):
    authorize(user, tenant, 'student.self')
    lock_tenant(tenant)
    student = student_for(user, tenant)
    if student is None:
        raise ValidationError('No tienes una ficha de estudiante vinculada.')
    session = SesionClase.objects.select_related('clase').filter(pk=session_id, clase__academia=tenant,
        estado='PROGRAMADA', fecha_hora_inicio__gt=timezone.now()).first()
    if session is None:
        raise ValidationError('La sesión no está disponible para reservas o cancelaciones.')
    reservation = ReservaEstudiante.unfiltered_objects.filter(academia=tenant, sesion=session, estudiante=user).first()
    if action == 'CANCELAR':
        if not reservation or not reservation.active:
            return 'No tenías una reserva activa.'
        if reservation.asistio:
            raise ValidationError('Una asistencia realizada no se cancela como reserva.')
        reservation.active = False
        reservation.save(update_fields=['active'])
        if reservation.charged_enrollment_id:
            InscripcionPlan.unfiltered_objects.filter(pk=reservation.charged_enrollment_id, academia=tenant).update(
                clases_restantes=F('clases_restantes') + 1)
            message = 'Reserva cancelada. La clase volvió al plan del que se descontó.'
        else:
            message = 'Reserva histórica cancelada. La academia debe revisar el plan original antes de reintegrar una clase.'
        record(tenant, user, 'class.reservation.cancelled', reservation.pk)
        return message
    if action != 'RESERVAR':
        raise ValidationError('Acción inválida.')
    if reservation and reservation.active:
        return 'Ya tienes un cupo reservado.'
    if ReservaEstudiante.unfiltered_objects.filter(sesion=session, active=True).count() >= session.clase.limite_cupos:
        raise ValidationError('Esta clase ya está llena.')
    today = timezone.localdate()
    enrollment = InscripcionPlan.unfiltered_objects.filter(academia=tenant, estudiante=student,
        cancelled_at=None, fecha_inicio__lte=today, fecha_fin__gte=today, clases_restantes__gt=0).order_by('fecha_fin', 'pk').first()
    if enrollment is None:
        raise ValidationError('No tienes clases disponibles en un plan vigente.')
    if not InscripcionPlan.unfiltered_objects.filter(pk=enrollment.pk, clases_restantes__gt=0).update(
            clases_restantes=F('clases_restantes') - 1):
        raise ValidationError('El plan ya no tiene clases disponibles.')
    if reservation:
        reservation.active, reservation.charged_enrollment = True, enrollment
        reservation.save(update_fields=['active', 'charged_enrollment'])
    else:
        reservation = ReservaEstudiante.unfiltered_objects.create(academia=tenant, sesion=session,
            estudiante=user, charged_enrollment=enrollment)
    record(tenant, user, 'class.reservation.created', reservation.pk)
    return 'Cupo reservado. La clase se descontó una sola vez de tu plan.'
