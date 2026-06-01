"""
URL configuration for gestoracademia project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.saas_core.views import (
    PanelMaestroDashboardView, 
    ActualizarLicenciaSaaSView,
    CrearAcademiaSaaSView,
    CrearPlanSaaSView,
    APIObtenerEstudiantesAcademiaView,
    IndexSaaSGlobalView,
    MasterActualizarLandingView
)

urlpatterns = [
    
    path('', IndexSaaSGlobalView.as_view(), name='saas_index_global'),
    path('master/control-panel/', PanelMaestroDashboardView.as_view(), name='panel_maestro_dashboard'),
    # 🎯 LA PIEZA FALTANTE: Endpoint POST para la actualización de licencias vía Fetch/AJAX
    path('master/control-panel/actualizar-licencia/', ActualizarLicenciaSaaSView.as_view(), name='actualizar_licencia'),

    # ➕ Endpoints de Creación Rápida
    path('master/control-panel/crear-academia/', CrearAcademiaSaaSView.as_view(), name='master_crear_academia'),
    path('master/control-panel/crear-plan/', CrearPlanSaaSView.as_view(), name='master_crear_plan'),
    path('master/actualizar-landing/', MasterActualizarLandingView.as_view(), name='master_actualizar_landing'),
    
    # 🔍 API secreta de soporte para visualización de estudiantes en modal
    path('master/control-panel/api-estudiantes/', APIObtenerEstudiantesAcademiaView.as_view(), name='api_estudiantes_academia'),
    path('admin/', admin.site.urls),
    # 🚀 Inclusión de las rutas de las academias con el prefijo dinámico
    path('', include('apps.academias.urls', namespace='academias')),
    # 🚀 ENGANCHAMOS LAS RUTAS DE ESTUDIANTES
    path('', include('apps.planes_estudiantes.urls', namespace='planes_estudiantes')),
    # 🚀 ENGANCHAMOS LAS RUTAS DE ASISTENCIA
    path('', include('apps.asistencias.urls', namespace='asistencias')),
    # gestoracademia/urls.py (Dentro de urlpatterns)
    path('', include('apps.finanzas.urls', namespace='finanzas')),
    path('', include('apps.eventos.urls')), # 👈 ENGANCHAMOS LAS URLS DE EVENTOS DE UNA
    path('', include('apps.multimedia.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)