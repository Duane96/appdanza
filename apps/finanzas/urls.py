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

    # 🆕 NUEVAS RUTAS AJAX Y REPORTES
    path('<slug:slug_academia>/finanzas/transaccion/ajax/<str:tipo>/<int:pk>/', views.ObtenerDetalleTransaccionView.as_view(), name='detalle_transaccion_ajax'),
    path('<slug:slug_academia>/finanzas/reportes/exportar/', views.ExportarReporteContableView.as_view(), name='exportar_reporte_contable'),
    path('<slug:slug_academia>/finanzas/reportes/resumen-ajax/', views.ResumenReporteAjaxView.as_view(), name='resumen_reporte_ajax'),

    # 🚀 RUTAS DE DESCARGA (Las que faltaban para arreglar el 404)
    path('<slug:slug_academia>/finanzas/descargar-pdf/<str:tipo>/<int:pk>/', views.DescargarReciboPDFView.as_view(), name='descargar_pdf'),
    path('<slug:slug_academia>/finanzas/reportes/descargar-zip/', views.DescargarSoportesZipView.as_view(), name='descargar_zip'),
]