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


urlpatterns = [
    
    
    

    path('admin/', admin.site.urls),

    path('', include('apps.saas_core.urls')),
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
    path('', include('apps.tienda.urls')),
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)