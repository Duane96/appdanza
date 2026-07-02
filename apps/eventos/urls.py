# apps/eventos/urls.py
from django.urls import path
from . import views

app_name = 'eventos'

urlpatterns = [
    # 🌍 Gestión de Eventos general (Ahora lee slug_academia)
    path('<slug:slug_academia>/eventos/', views.EventoListView.as_view(), name='admin_lista'),
    path('<slug:slug_academia>/eventos/crear/', views.EventoCreateView.as_view(), name='admin_crear'),
    
    # ⚙️ Centro de control del evento específico
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/', views.EventoDetailAdminView.as_view(), name='admin_detalle'),
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/estado/<str:nuevo_estado>/', views.cambiar_estado_evento, name='cambiar_estado'),
    
    # 💵 Acciones contables internas del evento
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/gasto/agregar/', views.AgregarGastoEventoView.as_view(), name='agregar_gasto'),
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/codigo/agregar/', views.AgregarCodigoDescuentoView.as_view(), name='agregar_codigo'),
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/taquilla/', views.RegistrarVentaPuertaView.as_view(), name='registrar_puerta'),
    # 🌍 Pasarela Pública de Inscripción para los Clientes
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/registro/', views.RegistroEventoPublicoView.as_view(), name='registro_publico'),

    # API de validación para el JavaScript en vivo
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/validar-cupon/', views.ValidarCuponAPIView.as_view(), name='api_validar_cupon'),

    # 🎫 Pantalla de agradecimiento con entrega de códigos QR individuales
    path('<slug:slug_academia>/eventos/inscripcion-exitosa/<int:recibo_id>/', views.RegistroExitoView.as_view(), name='registro_exito'),
    # 🔍 API Transaccional de Validación de Boletas QR en Puerta
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/validar-ingreso-qr/', views.ValidarIngresoQRAPIView.as_view(), name='api_validar_ingreso_qr'),

    # NUEVA RUTA: Edición del evento basada en la vista UpdateView
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/editar/', views.EventoUpdateView.as_view(), name='admin_editar'),

    path('<slug:slug_academia>/eventos/<slug:evento_slug>/agregar-pase/', views.AgregarTipoPaseView.as_view(), name='agregar_pase'),
    path('<slug:slug_academia>/eventos/<slug:evento_slug>/agregar-fase/', views.AgregarFasePreventaView.as_view(), name='agregar_fase'),

    path('<slug:slug_academia>/pases/<int:pk>/editar/', views.EditarTipoPaseView.as_view(), name='editar_pase'),
    path('<slug:slug_academia>/pases/<int:pk>/eliminar/', views.EliminarTipoPaseView.as_view(), name='eliminar_pase'),

    path('<slug:slug_academia>/eventos/<slug:evento_slug>/recibos/<int:recibo_id>/anular/', views.AnularReciboView.as_view(), name='anular_recibo'),
    path('<slug:slug_academia>/fases/<int:pk>/editar/', views.EditarFasePreventaView.as_view(), name='editar_fase'),
    path('<slug:slug_academia>/fases/<int:pk>/eliminar/', views.EliminarFasePreventaView.as_view(), name='eliminar_fase'),
]