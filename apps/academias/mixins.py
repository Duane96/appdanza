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
                if perfil.academia != request.tenant:
                    return render(request, 'academias/errores/acceso_denegado.html', status=403)
            except AttributeError:
                return render(request, 'academias/errores/acceso_denegado.html', status=403)

        return super().dispatch(request, *args, **kwargs)


class TenantAdminRequiredMixin(AccessMixin):
    """
    Mixin ESTRICTO: Solo permite el paso a los Administradores de la Academia.
    Bloquea totalmente a Estudiantes y Profesores.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_superuser:
            try:
                perfil = request.user.perfil
                if perfil.academia != request.tenant:
                    return render(request, 'academias/errores/acceso_denegado.html', status=403)
                
                # 🚀 EL CAMBIO CLAVE: Expulsamos al profesor de aquí
                if perfil.rol != 'ADMIN_ACADEMIA':
                    contexto = {'mensaje': 'Esta área es exclusiva para los dueños y administradores de la academia.'}
                    return render(request, 'academias/errores/acceso_denegado.html', contexto, status=403)
                    
            except AttributeError:
                return render(request, 'academias/errores/acceso_denegado.html', status=403)

        return super().dispatch(request, *args, **kwargs)


class TenantStaffRequiredMixin(AccessMixin):
    """
    Mixin HÍBRIDO: Úsalo solo en vistas donde tanto el Administrador 
    como el Profesor deban tener acceso (ej. Escanear QR de Asistencia).
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_superuser:
            try:
                perfil = request.user.perfil
                if perfil.academia != request.tenant:
                    return render(request, 'academias/errores/acceso_denegado.html', status=403)
                
                # Permite paso a Admin y Profe
                if perfil.rol not in ['ADMIN_ACADEMIA', 'PROFESOR']:
                    contexto = {'mensaje': 'Esta área es exclusiva para el personal y los instructores.'}
                    return render(request, 'academias/errores/acceso_denegado.html', contexto, status=403)
                    
            except AttributeError:
                return render(request, 'academias/errores/acceso_denegado.html', status=403)

        return super().dispatch(request, *args, **kwargs)