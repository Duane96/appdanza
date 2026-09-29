"""Deny-by-default authorization shared by views, services and background work."""
from functools import wraps
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import JsonResponse

LEGACY_ROLES = {'ADMIN_ACADEMIA': 'ADMIN', 'PROFESOR': 'TEACHER', 'ESTUDIANTE': 'STUDENT'}
ROLE_ACTIONS = {
    'OWNER': {'tenant.view', 'tenant.admin', 'tenant.staff', 'teacher.self', 'student.self',
              'billing.manage', 'events.view', 'events.metrics', 'events.manage', 'events.sell', 'events.checkin'},
    'ADMIN': {'tenant.view', 'tenant.admin', 'tenant.staff', 'teacher.self', 'student.self',
              'events.view', 'events.metrics', 'events.manage', 'events.sell', 'events.checkin'},
    'TEACHER': {'tenant.view', 'tenant.staff', 'teacher.self'},
    'STUDENT': {'tenant.view', 'student.self'},
    'BILLING': {'tenant.view', 'billing.manage'},
}
COLLABORATOR_ACTIONS = {
    'METRICAS': {'events.view', 'events.metrics'},
    'TAQUILLA': {'events.view', 'events.sell', 'events.checkin'},
}


def tenant_id_for(resource, depth=0):
    if resource is None or depth > 4:
        return None
    if getattr(getattr(resource, '_meta', None), 'label_lower', None) == 'academias.academia':
        return resource.pk
    if getattr(resource, 'academia_id', None) is not None:
        return resource.academia_id
    for name in ('evento', 'recibo', 'modulo', 'fase', 'fase_preventa', 'clase', 'sesion', 'estudiante', 'profesor',
                 'venta', 'producto', 'invoice', 'subscription', 'usage', 'admission', 'payment', 'receipt'):
        try:
            related = getattr(resource, name, None)
        except ObjectDoesNotExist:
            continue
        if related is not None and hasattr(related, '_meta'):
            found = tenant_id_for(related, depth + 1)
            if found is not None:
                return found
    return None


def membership_role(user, tenant):
    if not user.is_authenticated or not user.is_active or tenant is None:
        return None
    from .models import TenantMembership
    membership = TenantMembership.objects.filter(user_id=user.pk, academia_id=tenant.pk).first()
    if membership is not None:
        return membership.role if membership.active else None
    try:
        profile = user.perfil
        if profile.academia_id == tenant.pk:
            return LEGACY_ROLES.get(profile.rol)
    except ObjectDoesNotExist:
        pass
    return None


def can(user, tenant, action, resource=None):
    if not user.is_authenticated or not user.is_active:
        return False
    if tenant is None:
        return action == 'platform.manage' and user.is_superuser
    if not tenant.activo:
        return False
    if resource is not None and tenant_id_for(resource) != tenant.pk:
        return False
    if action not in set().union(*ROLE_ACTIONS.values()):
        return False
    if user.is_superuser:
        return True
    if action in ROLE_ACTIONS.get(membership_role(user, tenant), set()):
        return True
    if action.startswith('events.'):
        from apps.eventos.models import ColaboradorEvento
        collaborators = ColaboradorEvento.objects.filter(usuario_id=user.pk, evento__academia_id=tenant.pk)
        if resource is not None:
            event = resource if resource._meta.label_lower == 'eventos.evento' else getattr(resource, 'evento', None)
            if event is None:
                return False
            collaborators = collaborators.filter(evento_id=event.pk)
        elif action != 'events.view':
            return False
        return any(action in COLLABORATOR_ACTIONS.get(role, set()) for role in collaborators.values_list('rol', flat=True))
    return False


def authorize(user, tenant, action, resource=None):
    if not can(user, tenant, action, resource):
        raise PermissionDenied('No tienes permiso para realizar esta operación.')


def tenant_permission(action, tenant_getter=None):
    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            tenant = tenant_getter(request, **kwargs) if tenant_getter else getattr(request, 'tenant', None)
            if not can(request.user, tenant, action):
                return JsonResponse({'error': 'permission_denied'}, status=403)
            return view(request, *args, **kwargs)
        return guarded
    return decorate


def target_academy(request, **kwargs):
    from .models import Academia
    target = request.GET.get('academia_id') if request.method == 'GET' else request.POST.get('academia_id')
    return Academia.unfiltered_objects.filter(pk=target, activo=True).first() if str(target).isdigit() else None


def slug_academy(request, slug_academia, **kwargs):
    from .models import Academia
    return Academia.unfiltered_objects.filter(slug=slug_academia, activo=True).first()
