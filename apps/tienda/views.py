# apps/tienda/views.py
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.generic import ListView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.db import transaction
from django.contrib import messages

from .models import CategoriaProducto, Producto, VentaTienda, DetalleVenta, EntradaStock
from .forms import CategoriaProductoForm, ProductoForm, EntradaStockForm
from apps.finanzas.models import ReciboIngreso

from django.db.models import Sum, F, Q
import zoneinfo


import zoneinfo
from django.utils import timezone
from datetime import datetime, timedelta

class PuntoVentaPOSView(LoginRequiredMixin, ListView):
    template_name = "tienda/pos.html"
    context_object_name = "productos"

    def get_queryset(self):
        return Producto.objects.filter(academia=self.request.tenant, estado=True).select_related('categoria')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 🕒 1. CONTROL ESTRICTO DE ZONA HORARIA (Colombia)
        tz_col = zoneinfo.ZoneInfo('America/Bogota')
        now_col = timezone.now().astimezone(tz_col)

        # Calculamos el inicio y fin exacto del día actual en Colombia
        start_of_day = now_col.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # 2. Filtramos ventas dentro del rango de hoy en Colombia y excluímos recibos anulados/inexistentes
        ventas_hoy = VentaTienda.objects.filter(
            academia=self.request.tenant,
            fecha__gte=start_of_day,  # Mayor o igual a las 00:00:00 de hoy
            fecha__lt=end_of_day      # Estrictamente menor a las 00:00:00 de mañana
        ).exclude(
            Q(recibo_caja__isnull=True) | Q(recibo_caja__estado='ANULADO')
        )

        # 3. Sumatorias condicionales eficientes en base de datos
        resumen = ventas_hoy.aggregate(
            efectivo=Sum('total_venta', filter=Q(recibo_caja__medio_pago='EFECTIVO')),
            transferencia=Sum('total_venta', filter=Q(recibo_caja__medio_pago='TRANSFERENCIA')),
            tarjeta=Sum('total_venta', filter=Q(recibo_caja__medio_pago='TARJETA')),
            ganancia=Sum('total_ganancia')
        )

        context['categorias'] = CategoriaProducto.objects.filter(academia=self.request.tenant)
        context['inventario_global'] = Producto.objects.filter(academia=self.request.tenant).order_by('stock')
        context['entrada_form'] = EntradaStockForm(academia=self.request.tenant)
        context['categoria_form'] = CategoriaProductoForm()
        context['producto_form'] = ProductoForm(academia=self.request.tenant)

        # 4. Asignamos totales (fallback a 0 si resumen devuelve None)
        context['total_efectivo'] = resumen['efectivo'] or 0
        context['total_transferencia'] = resumen['transferencia'] or 0
        context['total_tarjeta'] = resumen['tarjeta'] or 0

        context['total_diario'] = context['total_efectivo'] + context['total_transferencia'] + context['total_tarjeta']
        context['ganancia_diaria'] = resumen['ganancia'] or 0

        return context


class ProcesarVentaPOSView(LoginRequiredMixin, View):
    """
    Endpoint asíncrono (AJAX / Fetch API) que procesa la compra del carrito,
    descuenta stock y emite de forma automática el recibo en la app de Finanzas.
    """
    def post(self, request, slug_academia):
        try:
            # Lectura del payload JSON enviado por JavaScript
            data = json.loads(request.body)
            carrito = data.get('carrito', []) # Formato esperado: [{"id": 1, "cantidad": 2}]
            medio_pago = data.get('medio_pago', 'EFECTIVO')
            cliente_nombre = data.get('cliente_nombre', 'Cliente General (POS)')
            cliente_nit = data.get('cliente_nit', '222222222222') # NIT de cuantías menores por defecto en Colombia

            if not carrito:
                return JsonResponse({'error': 'El carrito de compras está vacío.'}, status=400)

            # Usamos transacciones atómicas: si falla la venta de un solo producto, nada se guarda en la DB
            with transaction.atomic():
                # 1. Crear el registro maestro de la venta
                venta = VentaTienda.objects.create(
                    academia=request.tenant,
                    vendedor=request.user
                )

                # 2. Iterar e insertar cada fila del detalle del carrito
                for item in carrito:
                    prod_id = item.get('id')
                    cantidad = int(item.get('cantidad', 1))

                    if cantidad <= 0:
                        raise ValueError("La cantidad debe ser mayor a cero.")

                    # select_for_update() bloquea la fila del producto en la base de datos hasta que termine la transacción.
                    # Esto evita el error de condiciones de carrera (Race Conditions) si dos vendedores venden el último agua al mismo tiempo.
                    producto = Producto.objects.select_for_update().filter(academia=request.tenant, id=prod_id).first()

                    if not producto:
                        raise ValueError(f"El producto solicitado no existe en el catálogo.")

                    if producto.stock < cantidad:
                        raise ValueError(f"Stock insuficiente para '{producto.nombre}'. Disponibles: {producto.stock} unidades.")

                    # Crear detalle de la línea (el método save() del modelo descuenta el stock automáticamente)
                    DetalleVenta.objects.create(
                        venta=venta,
                        producto=producto,
                        cantidad=cantidad,
                        precio_unitario_venta=producto.precio_venta_actual,
                        costo_unitario_compra=producto.precio_compra_actual
                    )

                # Refrescamos la venta desde la base de datos para obtener los totales calculados por el modelo
                venta.refresh_from_db()

                # 3. CONEXIÓN AUTOMÁTICA CON FINANZAS: Emitir el Recibo de Caja
                recibo = ReciboIngreso.objects.create(
                    academia=request.tenant,
                    inscripcion=None,
                    tipo_ingreso='TIENDA', # Este sí es el campo correcto de tu modelo
                    concepto=f"Venta POS #{venta.id} - ({venta.detalles.count()} items)",
                    monto=venta.total_venta,
                    medio_pago=medio_pago,
                    cliente_nit=cliente_nit,
                    cliente_nombre=cliente_nombre
                )

                # Enlazamos el recibo generado de vuelta a la cabecera de la venta
                venta.recibo_caja = recibo
                venta.save()

            return JsonResponse({
                'success': True,
                'msg': f'Venta registrada con éxito. Recibo Generado: {recibo.numero_recibo}',
                'numero_recibo': recibo.numero_recibo
            })

        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Error crítico en pasarela interna: {str(e)}'}, status=500)


class PanelInventarioView(LoginRequiredMixin, ListView):
    """Muestra el catálogo general, existencias, alertas y compras del día"""
    template_name = "tienda/panel_inventario.html"
    context_object_name = "productos"

    def get_queryset(self):
        # ⚡ NUEVO: Anotamos el valor total del inventario por fila directo en SQL (Cantidad x Costo)
        # Esto nos permite tener `prod.valor_inventario` disponible en el HTML al instante.
        return Producto.objects.filter(academia=self.request.tenant).annotate(
            valor_inventario=F('stock') * F('precio_compra_actual')
        ).order_by('stock')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()

        context['total_productos'] = qs.count()
        context['productos_agotados'] = qs.filter(stock__lte=0).count()

        # 💰 NUEVO: Reporte de Capital Inmovilizado (Dinero en Bodega)
        # Sumamos la anotación anterior SOLO de los productos que sí tienen stock positivo
        capital = qs.filter(stock__gt=0).aggregate(total=Sum('valor_inventario'))['total'] or 0
        context['capital_inventario'] = capital

        # --- Métrica de Inversión / Compras del DÍA (Hora Colombia) ---
        tz_col = zoneinfo.ZoneInfo('America/Bogota')
        now_col = timezone.now().astimezone(tz_col)

        inversion = EntradaStock.objects.filter(
            producto__academia=self.request.tenant,
            fecha__year=now_col.year,
            fecha__month=now_col.month,
            fecha__day=now_col.day
        ).annotate(
            gasto_lote=F('cantidad') * F('precio_compra')
        ).aggregate(total=Sum('gasto_lote'))['total'] or 0

        context['inversion_hoy'] = inversion
        context['categorias'] = CategoriaProducto.objects.filter(academia=self.request.tenant)

        context['producto_form'] = ProductoForm(academia=self.request.tenant)
        context['categoria_form'] = CategoriaProductoForm()

        return context


class RegistrarEntradaStockView(LoginRequiredMixin, FormView):
    """Permite reabastecer el inventario de forma manual actualizando costos"""
    template_name = "tienda/entrada_stock.html"
    form_class = EntradaStockForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['academia'] = self.request.tenant  # Pasamos el tenant al formulario
        return kwargs

    def form_valid(self, form):
        entrada = form.save(commit=False)
        entrada.registrado_por = self.request.user
        entrada.save() # El método save() del modelo se encarga de sumarle las unidades al producto.
        messages.success(self.request, f"Entrada de stock registrada correctamente para {entrada.producto.nombre}.")
        return redirect('tienda:panel_inventario', slug_academia=self.request.tenant.slug)


class CrearCategoriaView(LoginRequiredMixin, View):
    """Procesa la creación rápida de una categoría desde el modal del POS"""
    def post(self, request, slug_academia):
        form = CategoriaProductoForm(request.POST)
        if form.is_valid():
            categoria = form.save(commit=False)
            categoria.academia = request.tenant
            categoria.save()
            messages.success(request, f"Categoría '{categoria.nombre}' creada.")
        else:
            messages.error(request, "Error al crear la categoría. Revisa los datos.")
        return redirect('tienda:pos', slug_academia=request.tenant.slug)

class CrearProductoView(LoginRequiredMixin, View):
    """Procesa la creación y le inyecta el stock inicial si el usuario lo solicita"""
    def post(self, request, slug_academia):
        form = ProductoForm(request.POST, academia=request.tenant)
        if form.is_valid():
            producto = form.save(commit=False)
            producto.academia = request.tenant
            producto.save() # Se crea en la base de datos (con stock 0 por defecto)

            # NUEVO: Lógica de Stock Inicial Automático
            stock_inicial = form.cleaned_data.get('stock_inicial', 0)
            if stock_inicial > 0:
                EntradaStock.objects.create(
                    producto=producto,
                    cantidad=stock_inicial,
                    precio_compra=producto.precio_compra_actual,
                    registrado_por=request.user
                ) # El save() de este modelo le suma el stock automáticamente al producto

            messages.success(request, f"Producto '{producto.nombre}' registrado con éxito.")
        else:
            messages.error(request, "Error al crear el producto. Revisa los datos.")

        # NUEVO: Redirección Inteligente (Vuelve a la página desde donde se envió el form)
        next_url = request.POST.get('next', reverse('tienda:pos', kwargs={'slug_academia': request.tenant.slug}))
        return redirect(next_url)

class EditarProductoView(LoginRequiredMixin, View):
    def post(self, request, slug_academia, pk):
        producto = get_object_or_404(Producto, id=pk, academia=request.tenant)
        form = ProductoForm(request.POST, instance=producto, academia=request.tenant)

        if form.is_valid():
            # FORZAMOS el estado: si el checkbox no vino, es False
            producto.estado = 'estado' in request.POST
            form.save()
            messages.success(request, f"Producto '{producto.nombre}' actualizado.")
        else:
            messages.error(request, "Error: " + str(form.errors))

        return redirect('tienda:panel_inventario', slug_academia=request.tenant.slug)


class ReporteVentasDiaView(LoginRequiredMixin, View):
    def get(self, request, slug_academia):
        fecha_str = request.GET.get('fecha')
        if not fecha_str:
            return JsonResponse({'error': 'Fecha requerida'}, status=400)

        tz_col = zoneinfo.ZoneInfo('America/Bogota')
        try:
            # Convertimos el string 'YYYY-MM-DD' del input HTML a un rango de datetimes en hora Colombia
            dt = datetime.strptime(fecha_str, '%Y-%m-%d')
            start_of_day = datetime(dt.year, dt.month, dt.day, tzinfo=tz_col)
            end_of_day = start_of_day + timedelta(days=1)
        except ValueError:
            return JsonResponse({'error': 'Formato de fecha inválido'}, status=400)

        # Aplicamos el mismo blindaje de rango y exclusión
        ventas = VentaTienda.objects.filter(
            academia=request.tenant,
            fecha__gte=start_of_day,
            fecha__lt=end_of_day
        ).exclude(
            Q(recibo_caja__isnull=True) | Q(recibo_caja__estado='ANULADO')
        )

        detalle_resumen = DetalleVenta.objects.filter(venta__in=ventas).values(
            'producto__nombre'
        ).annotate(
            total_qty=Sum('cantidad'),
            total_sub=Sum('subtotal'),
            total_gan=Sum('ganancia')
        )

        totales = ventas.aggregate(
            venta_final=Sum('total_venta'),
            ganancia_final=Sum('total_ganancia')
        )

        return JsonResponse({
            'total': float(totales['venta_final'] or 0),
            'ganancia': float(totales['ganancia_final'] or 0),
            'cantidad_ventas': ventas.count(),
            'detalles': list(detalle_resumen)
        })