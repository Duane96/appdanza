# apps/planes_estudiantes/templatetags/estudiante_extras.py
from django import template
from apps.planes_estudiantes.models import Estudiante

register = template.Library()

@register.simple_tag
def verificar_estado_estudiante(user, tenant):
    """Retorna el estado del estudiante ('ACTIVO' o 'INACTIVO') basado en su usuario real."""
    if not user.is_authenticated or not tenant:
        return 'INACTIVO'
        
    # Misma lógica blindada que usamos en el portal
    estudiante = Estudiante.objects.filter(
        nombres=user.first_name,
        apellidos=user.last_name,
        academia=tenant
    ).first()
    
    if not estudiante and user.email:
        estudiante = Estudiante.objects.filter(
            email__iexact=user.email,
            academia=tenant
        ).first()
        
    if estudiante:
        return estudiante.estado
        
    return 'INACTIVO'