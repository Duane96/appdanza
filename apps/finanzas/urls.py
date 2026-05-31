# apps/finanzas/urls.py
from django.urls import path
from . import views

app_name = 'finanzas'

urlpatterns = [
    path('<slug:slug_academia>/finanzas/', views.PanelFinanzasView.as_view(), name='panel_finanzas'),
    path('<slug:slug_academia>/finanzas/gasto/nuevo/', views.RegistrarGastoView.as_view(), name='registrar_gasto'),
    path('<slug:slug_academia>/finanzas/ingreso/nuevo/', views.RegistrarIngresoExtraView.as_view(), name='registrar_ingreso'),
    path('<slug:slug_academia>/finanzas/profesor/liquidar/', views.LiquidarProfesorView.as_view(), name='liquidar_profesor'),
    path('<slug:slug_academia>/finanzas/anular/<str:tipo>/<int:pk>/', views.AnularTransaccionView.as_view(), name='anular_transaccion'),
]