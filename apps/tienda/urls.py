# apps/tienda/urls.py
from django.urls import path
from . import views

app_name = 'tienda'

urlpatterns = [
    # Interfaz Interactiva de Ventas Rápidas (POS)
    path('<slug:slug_academia>/tienda/pos/', views.PuntoVentaPOSView.as_view(), name='pos'),
    path('<slug:slug_academia>/tienda/pos/pagar/', views.ProcesarVentaPOSView.as_view(), name='procesar_venta_pos'),
    
    # Backoffice y Administración de Inventarios
    path('<slug:slug_academia>/tienda/inventario/', views.PanelInventarioView.as_view(), name='panel_inventario'),
    path('<slug:slug_academia>/tienda/inventario/entrada/', views.RegistrarEntradaStockView.as_view(), name='registrar_entrada'),

    # --- NUEVAS RUTAS PARA CREACIÓN RÁPIDA ---
    path('<slug:slug_academia>/tienda/categoria/crear/', views.CrearCategoriaView.as_view(), name='crear_categoria'),
    path('<slug:slug_academia>/tienda/producto/crear/', views.CrearProductoView.as_view(), name='crear_producto'),

    path('<slug:slug_academia>/tienda/producto/<int:pk>/editar/', views.EditarProductoView.as_view(), name='editar_producto'),

    path('<slug:slug_academia>/tienda/reporte-dia/', views.ReporteVentasDiaView.as_view(), name='reporte_dia'),
]