# gestoracademia/middleware.py
from django.http import Http404
from django.urls import resolve
# 🛠️ Eliminamos la línea que causaba el error y dejamos solo las importaciones limpias:
from apps.academias.models import Academia
from gestoracademia.tenants import set_current_tenant, clear_current_tenant

class TenantMiddleware:
    """
    Middleware encargado de capturar el slug de la academia desde la URL,
    validar su existencia e inyectarla en el hilo de la petición actual.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Resolvemos la ruta actual para verificar si incluye la variable 'slug_academia'
        match = resolve(request.path_info)
        slug_academia = match.kwargs.get('slug_academia')

        if slug_academia:
            try:
                # Buscamos la academia activa
                academia = Academia.unfiltered_objects.get(slug=slug_academia, activo=True)
                
                # Inyectamos la academia en el request y en el hilo seguro
                request.tenant = academia
                set_current_tenant(academia)
                
            except Academia.DoesNotExist:
                raise Http404("La academia solicitada no existe o se encuentra inactiva.")
        else:
            request.tenant = None
            clear_current_tenant()

        response = self.get_response(request)
        
        # Limpieza absoluta al terminar el ciclo de la petición
        clear_current_tenant()
        return response