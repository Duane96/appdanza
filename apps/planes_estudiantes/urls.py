# apps/planes_estudiantes/urls.py
from django.urls import path
from . import views

app_name = 'planes_estudiantes'

urlpatterns = [
    path('<slug:slug_academia>/estudiantes/', views.ListaEstudiantesView.as_view(), name='lista_estudiantes'),
    path('<slug:slug_academia>/estudiantes/nuevo/', views.CrearEstudianteView.as_view(), name='crear_estudiante'),
    path('<slug:slug_academia>/estudiantes/asignar-plan/', views.AsignarPlanView.as_view(), name='asignar_plan'),
    path('<slug:slug_academia>/portal/', views.PortalEstudianteView.as_view(), name='portal_estudiante'),
    path('<slug:slug_academia>/planes/crear/', views.CrearPlanView.as_view(), name='crear_plan'),
    path('<slug:slug_academia>/api/estudiante/<int:est_id>/', views.api_detalle_estudiante, name='api_estudiante'),
]