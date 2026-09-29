"""Route boundary: tenant routes are private unless explicitly public.

Services and sensitive views also authorize independently. This boundary prevents
new tenant views from accidentally becoming public through an omitted mixin.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.deprecation import MiddlewareMixin
from .authorization import can, membership_role
from .models import Academia

PUBLIC_ROUTES = {
    'saas_core:onboarding_signup', 'saas_core:onboarding_verify',
    'saas_core:epayco_confirmation',
    'academias:accept_invitation',
    'academias:index', 'academias:login',
    'eventos:registro_publico', 'eventos:api_validar_cupon', 'eventos:master_league',
    # The success view verifies its own purpose-bound signed receipt capability.
    'eventos:registro_exito', 'eventos:quote',
    'saas_core:saas_index_global', 'saas_core:procesar_lead_landing',
    'dya_events', 'dya_event', 'private_media',
}
TENANT_ACTIONS = {
    'saas_core:billing_mandate': 'billing.manage',
    'saas_core:billing_portal': 'billing.manage', 'saas_core:billing_select_plan': 'billing.manage',
    'saas_core:billing_cancel': 'billing.manage', 'saas_core:billing_proof': 'billing.manage',
    'academias:logout': 'tenant.view', 'academias:cambiar_password': 'tenant.view',
    'planes_estudiantes:portal_estudiante': 'student.self',
    'multimedia:visor_clase': 'tenant.view',
    'calendario:estudiante_calendario': 'student.self',
    'calendario:ajax_reservar_clase': 'student.self',
    'calendario:profesor_calendario': 'teacher.self',
    'profesores:dashboard_profesor': 'teacher.self',
    'profesores:ajax_cuenta_cobro': 'teacher.self',
    'eventos:admin_lista': 'events.view', 'eventos:admin_detalle': 'events.view',
    'eventos:api_validar_ingreso_qr': 'events.checkin',
    'eventos:api_buscar_asistente': 'events.checkin',
    'eventos:registrar_puerta': 'events.sell',
}


class TenantAuthorizationMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        route = request.resolver_match.view_name
        if route in PUBLIC_ROUTES:
            return None
        tenant = getattr(request, 'tenant', None)
        # Legacy global URL, with the tenant selected in data: authorize that
        # exact target, never a profile's unrelated default academy.
        if route in {'saas_core:api_finanzas_academia', 'saas_core:api_subir_comprobante'}:
            target = request.GET.get('academia_id') if request.method == 'GET' else request.POST.get('academia_id')
            if not target or not str(target).isdigit():
                return JsonResponse({'error': 'invalid_academy'}, status=403)
            tenant = Academia.unfiltered_objects.filter(pk=target, activo=True).first()
            action = 'tenant.admin' if route.endswith('api_finanzas_academia') else 'billing.manage'
            allowed = can(request.user, tenant, action)
        elif tenant:
            action = TENANT_ACTIONS.get(route, 'events.manage' if route.startswith('eventos:') else 'tenant.admin')
            resource = None
            if route.startswith('eventos:') and view_kwargs.get('evento_slug'):
                from apps.eventos.models import Evento
                resource = get_object_or_404(Evento.unfiltered_objects, academia_id=tenant.pk, slug=view_kwargs['evento_slug'])
            allowed = can(request.user, tenant, action, resource)
            request.membership_role = membership_role(request.user, tenant)
        else:
            if route in {'admin:login', 'admin:logout'}:
                return None
            allowed = can(request.user, None, 'platform.manage')
        if not allowed:
            return JsonResponse({'error': 'permission_denied'}, status=403)
        if tenant:
            from apps.saas_core.policy import EntitlementService
            from apps.saas_core.models import BillingAccount
            from django.core.exceptions import PermissionDenied
            namespace = route.split(':')[0]
            module = {'planes_estudiantes': 'estudiantes', 'eventos': 'eventos', 'finanzas': 'finanzas',
                'multimedia': 'multimedia', 'asistencias': 'asistencias', 'calendario': 'calendario',
                'profesores': 'profesores', 'tienda': 'tienda'}.get(namespace)
            # Existing rows receive an explicit snapshot in the data migration.
            # Operational attendance and already-sold event access stay available
            # during dunning; creation is constrained in the transaction boundary.
            if module and BillingAccount.objects.filter(academia=tenant).exists():
                EntitlementService(tenant).require(module)
        return None
