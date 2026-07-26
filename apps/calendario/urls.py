# apps/calendario/urls.py
from django.urls import path
from . import views

app_name = 'calendario'

urlpatterns = [
    # 🚀 Endpoint AJAX para marcar la clase y gestionar el pago
    path('ajax/marcar-dictada/', views.MarcarClaseDictadaView.as_view(), name='ajax_marcar_dictada'),
    
    # -----------------------------------------------------
    # RUTAS ADMINISTRADOR / STAFF
    # -----------------------------------------------------
    # Ej: /distrito-social/calendario/admin/
    path('admin/', views.CalendarioAdminView.as_view(), name='admin_calendario'),
    # -----------------------------------------------------
    # RUTAS ESTUDIANTES
    # -----------------------------------------------------
    # Ej: /distrito-social/calendario/
    path('', views.CalendarioEstudianteView.as_view(), name='estudiante_calendario'),
    
    # Endpoint AJAX (Botón Reservar)
    path('ajax/reservar/', views.ReservarClaseView.as_view(), name='ajax_reservar_clase'),

    # NUEVAS RUTAS DE CREACIÓN:
    path('admin/clase/nueva/', views.CrearClaseView.as_view(), name='crear_clase'),
    path('admin/sesion/nueva/', views.CrearSesionClaseView.as_view(), name='crear_sesion'),

    # GESTIÓN DE CLASES BASE (NUEVAS)
    path('admin/clases/', views.ListaClasesView.as_view(), name='lista_clases'),
    path('admin/clase/editar/<int:pk>/', views.EditarClaseView.as_view(), name='editar_clase'),

    # NUEVA RUTA DE EXCEPCIONES:
    path('admin/sesion/excepcion/<int:pk>/', views.EditarExcepcionSesionView.as_view(), name='excepcion_sesion'),

    # NUEVO: Endpoint Feed JSON para FullCalendar
    path('admin/feed-eventos/', views.CalendarioEventosJSONView.as_view(), name='feed_eventos_json'),
    path('mi-agenda/', views.CalendarioProfesorView.as_view(), name='profesor_calendario'),

    # Endpoint AJAX para el modal de agendamiento rápido
    path('admin/ajax/agendar-sesion/', views.ProgramarSesionAjaxView.as_view(), name='ajax_agendar_sesion'),
]