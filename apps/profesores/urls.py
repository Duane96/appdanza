# apps/profesores/urls.py
from django.urls import path
from . import views
# from .views import ListaProfesoresView # La crearemos pronto

app_name = 'profesores'

urlpatterns = [
    # Ruta para el listado del panel admin (Dashboard Profesores)
    # path('', ListaProfesoresView.as_view(), name='lista'),
    
    # Ruta para el formulario de creación
    path('crear/', views.CrearProfesorView.as_view(), name='crear_profesor'),
    # 📋 Listado principal (Dashboard Admin > Profesores)
    path('', views.ListaProfesoresView.as_view(), name='lista'),
    
    # ➕ Formulario de creación
    path('crear/', views.CrearProfesorView.as_view(), name='crear_profesor'),
    
    # ❌ Desactivar (Soft Delete) - Espera un POST por seguridad
    path('desactivar/<int:pk>/', views.DesactivarProfesorView.as_view(), name='desactivar_profesor'),
    path('activar/<int:pk>/', views.ActivarProfesorView.as_view(), name='activar_profesor'),
    # En apps/profesores/urls.py (agrega esta línea)
    path('mi-panel/', views.DashboardProfesorView.as_view(), name='dashboard_profesor'),
    path('ajax/cuenta-cobro/', views.ProcesarCuentaCobroView.as_view(), name='ajax_cuenta_cobro'),
    path('ajax/pagar-cuenta/', views.PagarCuentaCobroAdminView.as_view(), name='ajax_pagar_cuenta'),
    
]