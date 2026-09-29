from django.contrib.auth.mixins import AccessMixin
from .authorization import authorize


class TenantAccessMixin(AccessMixin):
    permission_action = 'tenant.view'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        authorize(request.user, getattr(request, 'tenant', None), self.permission_action)
        return super().dispatch(request, *args, **kwargs)


class TenantAdminRequiredMixin(TenantAccessMixin):
    permission_action = 'tenant.admin'


class TenantStaffRequiredMixin(TenantAccessMixin):
    permission_action = 'tenant.staff'


class EventPermissionMixin(AccessMixin):
    permission_action = 'events.manage'

    def dispatch(self, request, *args, **kwargs):
        from apps.eventos.models import Evento
        from django.shortcuts import get_object_or_404
        event = None
        if kwargs.get('evento_slug'):
            event = get_object_or_404(Evento.unfiltered_objects, academia=request.tenant, slug=kwargs['evento_slug'])
        authorize(request.user, getattr(request, 'tenant', None), self.permission_action, event)
        request.authorized_event = event
        return super().dispatch(request, *args, **kwargs)
