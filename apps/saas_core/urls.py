from django.urls import path
from . import views

app_name = 'saas_core'

urlpatterns = [
    path('', views.IndexSaaSGlobalView.as_view(), name='saas_index_global'),
    path('master/control-panel/', views.PanelMaestroDashboardView.as_view(), name='panel_maestro_dashboard'),
    # 🎯 LA PIEZA FALTANTE: Endpoint POST para la actualización de licencias vía Fetch/AJAX
    path('master/control-panel/actualizar-licencia/', views.ActualizarLicenciaSaaSView.as_view(), name='actualizar_licencia'),

    # ➕ Endpoints de Creación Rápida
    path('master/control-panel/crear-academia/', views.CrearAcademiaSaaSView.as_view(), name='master_crear_academia'),
    path('master/control-panel/crear-plan/', views.CrearPlanSaaSView.as_view(), name='master_crear_plan'),
    path('master/actualizar-landing/', views.MasterActualizarLandingView.as_view(), name='master_actualizar_landing'),
    
    # 🔍 API secreta de soporte para visualización de estudiantes en modal
    path('master/control-panel/api-estudiantes/', views.APIObtenerEstudiantesAcademiaView.as_view(), name='api_estudiantes_academia'),
    path('api/toggle-bloqueo/', views.ToggleBloqueoSaaSView.as_view(), name='api_toggle_bloqueo'),

    path('master/api/finanzas/', views.api_finanzas_academia, name='api_finanzas_academia'),
    path('master/plan/eliminar/<int:plan_id>/', views.EliminarPlanSaaSView.as_view(), name='master_eliminar_plan'),
    path('master/plan/editar/<int:plan_id>/', views.EditarPlanSaaSView.as_view(), name='master_editar_plan'),
    path('configuracion-pago/', views.GuardarConfigPagoGlobalView.as_view(), name='master_guardar_pago_global'),

    path('api/subir-comprobante/', views.SubirComprobanteSaaSView.as_view(), name='api_subir_comprobante'),
    path('pago/revision/<int:pk>/', views.RevisarYAprobarPagoView.as_view(), name='master_revisar_pago'),

    path('master/finanzas/', views.FinanzasMaestroDashboardView.as_view(), name='master_finanzas'),
    path('master/finanzas/recibo/<int:recibo_id>/pdf/', views.DescargarReciboSaaSPDFView.as_view(), name='master_descargar_recibo_pdf'),

    # 🚀 NUEVAS RUTAS DE FINANZAS MASTER:
    path('master/finanzas/gasto/nuevo/', views.RegistrarGastoSaaSView.as_view(), name='master_registrar_gasto'),
    path('master/finanzas/transaccion/ajax/<str:tipo>/<int:pk>/', views.ObtenerDetalleTransaccionSaaSView.as_view(), name='master_detalle_transaccion_ajax'),
    path('master/finanzas/exportar-csv/', views.ExportarContabilidadSaaSView.as_view(), name='master_exportar_csv'),

    path('master/asignar-plan/', views.MasterAsignarYRenovarPlanView.as_view(), name='master_asignar_plan'),
]