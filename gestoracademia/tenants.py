# core/tenants.py
from asgiref.local import Local

# Instancia de Local para almacenar datos específicos del hilo/corrutina actual
_tenant_storage = Local()

def set_current_tenant(academia):
    """Guarda la academia actual de la petición en el almacenamiento local."""
    _tenant_storage.current_tenant = academia

def get_current_tenant():
    """Recupera la academia actual de la petición. Retorna None si no está definida."""
    return getattr(_tenant_storage, 'current_tenant', None)

def clear_current_tenant():
    """Limpia el almacenamiento al finalizar la petición para evitar fugas de memoria."""
    if hasattr(_tenant_storage, 'current_tenant'):
        del _tenant_storage.current_tenant