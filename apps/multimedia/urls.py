# apps/multimedia/urls.py
from django.urls import path
from . import views

app_name = 'multimedia'

urlpatterns = [
    # 🌍 RUTA GLOBAL FIJA PARA GOOGLE OAUTH CALLBACK
    path('oauth2callback/', views.GoogleOAuthCallbackView.as_view(), name='google_oauth_callback'),
    
    # 1. Estudiante
    path('<slug:slug_academia>/visor/<int:modulo_id>/', views.VisorClaseView.as_view(), name='visor_clase'),
    
    # 2. Administrador: Gestión de Módulos (Clases)
    path('<slug:slug_academia>/control/clases/', views.ListaModulosAdminView.as_view(), name='lista_clases_admin'),
    path('<slug:slug_academia>/control/clases/nueva/', views.CrearModuloAdminView.as_view(), name='crear_clase'),
    path('<slug:slug_academia>/control/clases/<int:pk>/editar/', views.EditarModuloAdminView.as_view(), name='editar_clase'),
    path('<slug:slug_academia>/control/clases/<int:pk>/eliminar/', views.EliminarModuloAdminView.as_view(), name='eliminar_clase'),
    
    # 3. Administrador: Subida y Gestión de Videos
    path('<slug:slug_academia>/control/subir-video/', views.SubirVideoAdminView.as_view(), name='subir_video'),
    path('<slug:slug_academia>/control/videos/<int:pk>/editar/', views.EditarVideoAdminView.as_view(), name='editar_video'),
    path('<slug:slug_academia>/control/videos/<int:pk>/eliminar/', views.EliminarVideoAdminView.as_view(), name='eliminar_video'),
]