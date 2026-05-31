# apps/multimedia/urls.py
from django.urls import path
from . import views

app_name = 'multimedia'

urlpatterns = [
    # 1. Estudiante
    path('<slug:slug_academia>/visor/<int:modulo_id>/', views.VisorClaseView.as_view(), name='visor_clase'),
    
    # 2. Administrador: Gestión de Clases
    path('<slug:slug_academia>/control/clases/', views.ListaModulosAdminView.as_view(), name='lista_clases_admin'),
    path('<slug:slug_academia>/control/clases/nueva/', views.CrearModuloAdminView.as_view(), name='crear_clase'),
    
    # 3. Administrador: Subida de Videos
    path('<slug:slug_academia>/control/subir-video/', views.SubirVideoAdminView.as_view(), name='subir_video'),
]