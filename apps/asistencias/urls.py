# apps/asistencias/urls.py
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from . import views

app_name = 'asistencias'

urlpatterns = [
    # Pantalla del escáner: web.com/duane-y-aleja/asistencia/escaner/
    path('<slug:slug_academia>/asistencia/escaner/', views.PanelEscanerView.as_view(), name='panel_escaner'),
    
    # Endpoint de la API (La llamaremos vía JavaScript Fetch)
    path('<slug:slug_academia>/asistencia/api/procesar-qr/', views.ProcesarEscaneoQRView.as_view(), name='api_procesar_qr'),

    path('<slug:slug_academia>/asistencia/api/manual/', views.ProcesarAsistenciaManualView.as_view(), name='api_manual'),
]