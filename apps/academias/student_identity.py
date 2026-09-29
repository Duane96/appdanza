"""Explicit student identity with a constrained read-only legacy fallback."""
from .authorization import membership_role


def student_for(user, tenant):
    from apps.planes_estudiantes.models import Estudiante
    from .models import PerfilUsuario
    if not tenant or membership_role(user, tenant) != 'STUDENT':
        return None
    students = Estudiante.unfiltered_objects.filter(academia=tenant)
    explicit = students.filter(user=user).first()
    if explicit:
        return explicit
    # No automatic backfill by name/email. Existing accounts retain read access
    # only where both sides of their former identity rule are unambiguous.
    if not user.first_name or not user.last_name:
        return None
    peers = PerfilUsuario.objects.filter(academia=tenant, rol='ESTUDIANTE',
        user__first_name__iexact=user.first_name, user__last_name__iexact=user.last_name)
    candidates = students.filter(user=None, nombres__iexact=user.first_name, apellidos__iexact=user.last_name)
    if peers.count() > 1 or candidates.count() > 1:
        if not user.email:
            return None
        peers = peers.filter(user__email__iexact=user.email)
        candidates = candidates.filter(email__iexact=user.email)
    if peers.count() == 1 and peers.get().user_id == user.pk and candidates.count() == 1:
        return candidates.get()
    return None


def user_for_student(student):
    if student.user_id:
        return student.user
    from .models import PerfilUsuario
    candidates = PerfilUsuario.objects.filter(academia=student.academia, rol='ESTUDIANTE',
        user__first_name__iexact=student.nombres, user__last_name__iexact=student.apellidos).select_related('user')
    matches = [p.user for p in candidates if student_for(p.user, student.academia) == student]
    return matches[0] if len(matches) == 1 else None
