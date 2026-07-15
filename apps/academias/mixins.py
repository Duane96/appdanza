# apps/academias/mixins.py
from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import render

class TenantAccessMixin(AccessMixin):
    """Garantiza que el usuario pertenezca estrictamente a la academia actual."""
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_superuser:
            try:
                perfil = request.user.perfil
                # 🚨 Si el tenant de la URL NO es la academia del usuario
                if perfil.academia != request.tenant:
                    # En lugar de romper, renderizamos la pantalla amigable (Error 403 controlado)
                    return render(request, 'academias/errores/acceso_denegado.html', status=403)
            except AttributeError:
                return render(request, 'academias/errores/acceso_denegado.html', status=403)

        return super().dispatch(request, *args, **kwargs)


class TenantAdminRequiredMixin(AccessMixin):
    """Valida el Tenant y ADEMÁS exige que tenga rol de administrador o profesor."""
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_superuser:
            try:
                perfil = request.user.perfil
                
                # 1. Validamos cruce de academias
                if perfil.academia != request.tenant:
                    return render(request, 'academias/errores/acceso_denegado.html', status=403)
                
                # 2. Validamos que no sea un estudiante fisgoneando
                if perfil.rol not in ['ADMIN_ACADEMIA', 'PROFESOR']:
                    contexto = {'mensaje': 'Esta área es exclusiva para el personal administrativo y profesores.'}
                    return render(request, 'academias/errores/acceso_denegado.html', contexto, status=403)
                    
            except AttributeError:
                return render(request, 'academias/errores/acceso_denegado.html', status=403)

        # Si pasa todas las pruebas, ejecuta la vista normal
        return super().dispatch(request, *args, **kwargs)