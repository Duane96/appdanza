# apps/eventos/views.py
from django.http import JsonResponse
from django.views.generic import ListView, CreateView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.db.models import Sum, Q

from .models import Evento, CodigoDescuento, ReciboEvento, GastoEvento
from .forms import EventoForm, CodigoDescuentoForm, GastoEventoForm, VentaPuertaForm

from django.views.generic import FormView
from .forms import RegistroOnlineEventoForm
from apps.academias.models import Academia

from django.views.generic import TemplateView

import qrcode
import base64
from io import BytesIO

from django.utils import timezone
from .models import EntradaQR

from django.views.generic import UpdateView

from apps.comunicaciones.services import enviar_correo_transaccional

class EventoListView(LoginRequiredMixin, ListView):
    """Lista todos los eventos de la academia (Tenant actual)."""
    model = Evento
    template_name = "eventos/admin_list.html"
    context_object_name = "eventos"

    def get_queryset(self):
        # request.tenant inyectado de forma segura por el Middleware al hacer match con slug_academia
        return Evento.objects.filter(academia=self.request.tenant)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Esto es lo que faltaba para que tu template tuviera acceso a los campos
        context['form'] = EventoForm() 
        return context


class EventoCreateView(LoginRequiredMixin, CreateView):
    model = Evento
    form_class = EventoForm
    template_name = "eventos/admin_list.html" # Ahora renderizas el listado

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Inyectamos el formulario en el contexto del listado
        context['form'] = self.get_form()
        return context

    def form_valid(self, form):
        evento = form.save(commit=False)
        evento.academia = self.request.tenant
        evento.save()
        form.save_m2m()
        return redirect('eventos:admin_lista', slug_academia=self.request.tenant.slug)


class EventoUpdateView(LoginRequiredMixin, UpdateView):
    """Vista para editar un evento existente garantizando aislamiento estricto."""
    model = Evento
    form_class = EventoForm
    template_name = "eventos/admin_form.html" # REUTILIZA el mismo template

    def get_object(self):
        # Filtro estricto Multi-Tenant: nadie puede editar el evento de otra academia cambiando argumentos en la URL
        return get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])

    def form_valid(self, form):
        evento = form.save(commit=False)
        evento.academia = self.request.tenant 
        
        # Generamos el slug basado en el nombre (por si lo editaron)
        base_slug = slugify(evento.nombre)
        evento.slug = base_slug
        
        # 🐛 REPARACIÓN SENIOR: 
        # Añadimos .exclude(pk=evento.pk) para que al validar si el nombre ya existe, 
        # la base de datos IGNORE el evento que estamos editando actualmente.
        if Evento.objects.filter(academia=self.request.tenant, slug=base_slug).exclude(pk=evento.pk).exists():
            form.add_error('nombre', 'Ya existe OTRO evento con este nombre en tu calendario.')
            return self.form_invalid(form)
            
        evento.save()
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('eventos:admin_detalle', kwargs={
            'slug_academia': self.request.tenant.slug,
            'evento_slug': self.object.slug
        })


class EventoDetailAdminView(LoginRequiredMixin, DetailView):
    """
    Vista Senior encargada de renderizar el centro de mando contable de un evento.
    Calcula ingresos por medio de pago, egresos, asistencia real y las comisiones SaaS.
    """
    model = Evento
    template_name = "eventos/admin_detail.html"
    context_object_name = "evento"

    def get_object(self):
        # Filtro estricto Multi-Tenant usando el request.tenant del Middleware
        return get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        evento = self.object

        # 🔍 1. BUSCADOR DE RECIBOS POR FILTRO DE TEXTO (Aislado al evento)
        query = self.request.GET.get('q')
        recibos = ReciboEvento.objects.filter(evento=evento).order_by('-id')
        if query:
            recibos = recibos.filter(
                Q(comprador_nombre__icontains=query) | 
                Q(numero_recibo__icontains=query) |
                Q(comprador_telefono__icontains=query)
            )
        context['recibos'] = recibos
        context['q'] = query or ''

        # 💵 2. MÉTRICAS CONTABLES GENERALES EN TIEMPO REAL (Módulo Finanzas)
        context['total_entradas_vendidas'] = ReciboEvento.objects.filter(evento=evento).aggregate(total=Sum('cantidad_entradas'))['total'] or 0
        context['dinero_efectivo'] = ReciboEvento.objects.filter(evento=evento, medio_pago='EFECTIVO').aggregate(total=Sum('monto_total'))['total'] or 0
        context['dinero_transferencia'] = ReciboEvento.objects.filter(evento=evento, medio_pago='TRANSFERENCIA').aggregate(total=Sum('monto_total'))['total'] or 0
        context['dinero_tarjeta'] = ReciboEvento.objects.filter(evento=evento, medio_pago='TARJETA').aggregate(total=Sum('monto_total'))['total'] or 0
        
        # Total global recolectado de forma física en la Taquilla de Puerta
        dinero_en_puerta = ReciboEvento.objects.filter(evento=evento, origen='PUERTA').aggregate(total=Sum('monto_total'))['total'] or 0
        context['dinero_en_puerta'] = dinero_en_puerta
        
        # Ingresos totales brutos del evento (Online + Puerta)
        ingresos_totales = ReciboEvento.objects.filter(evento=evento).aggregate(total=Sum('monto_total'))['total'] or 0
        context['ingresos_totales'] = ingresos_totales

        # 🎯 3. DESGLOSE ESPECÍFICO DE DINERO ADQUIRIDO EN TAQUILLA (PUERTA)
        context['puerta_efectivo'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='EFECTIVO').aggregate(total=Sum('monto_total'))['total'] or 0
        context['puerta_transferencia'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='TRANSFERENCIA').aggregate(total=Sum('monto_total'))['total'] or 0
        context['puerta_tarjeta'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='TARJETA').aggregate(total=Sum('monto_total'))['total'] or 0

        # 🔴 4. REPORTE DE EGRESOS E INVERSIONES DEL EVENTO
        gastos = GastoEvento.objects.filter(evento=evento).order_by('-id')
        context['gastos'] = gastos
        gastos_totales = gastos.aggregate(total=Sum('monto'))['total'] or 0
        context['gastos_totales'] = gastos_totales

        # 📈 5. BALANCE NETO DE OPERACIÓN DE LA ACADEMIA
        context['balance_neto'] = ingresos_totales - gastos_totales
        context['codigos'] = CodigoDescuento.objects.filter(evento=evento)

        # 📥 6. CONTADOR DE ASISTENCIA REAL MEDIANTE LOG DE ACCESOS
        # Sumamos los registros que ya cruzaron la puerta escaneando su QR online
        # ✅ CORRECCIÓN: Filtramos usando los campos reales de la BD
        total_ingresos_qr = EntradaQR.objects.filter(
            recibo__evento=evento, 
            asistencias_consumidas__gt=0
        ).count()
        
        # Sumamos la cantidad de entradas vendidas directo en puerta que ya pasaron al salón
        ingresos_puerta_data = ReciboEvento.objects.filter(
            evento=evento, 
            origen='PUERTA', 
            ingresado_puerta=True
        ).aggregate(total_personas=Sum('cantidad_entradas'))
        
        total_ingresos_puerta = ingresos_puerta_data['total_personas'] or 0
        context['total_personas_ingresadas'] = total_ingresos_qr + total_ingresos_puerta

        # 👑 7. COMPUTO INTEGRAL DE COMISIONES PARA EL CARD DE TEMPO HUB (FASE BETA)
        # Consume la función del modelo encargada de evaluar tarifas mínimas o el modo Partner gratis
        comisiones_data = evento.calcular_estado_comisiones()
        context['saas_online_personas'] = comisiones_data['total_online']
        context['saas_puerta_personas'] = comisiones_data['total_puerta']
        context['saas_deuda_online'] = comisiones_data['deuda_online']
        context['saas_deuda_puerta'] = comisiones_data['deuda_puerta']
        context['saas_es_minima_online'] = comisiones_data['es_minima_online']
        context['saas_divisa'] = comisiones_data['divisa']
        context['saas_modo_partner'] = comisiones_data.get('modo_partner', False)
        context['saas_total_comision_evento'] = comisiones_data['deuda_online'] + comisiones_data['deuda_puerta']

        # 📥 8. INYECCIÓN DE INSTANCIAS DE FORMULARIOS PARA LOS MODALES FLOTANTES EN BOOTSTRAP
        context['form_gasto'] = GastoEventoForm()
        context['form_codigo'] = CodigoDescuentoForm()
        context['form_puerta'] = VentaPuertaForm(initial={
            'precio_unitario_aplicado': evento.precio_puerta,
            'cantidad_entradas': 1
        })

        return context


class AgregarGastoEventoView(LoginRequiredMixin, CreateView):
    model = GastoEvento
    form_class = GastoEventoForm

    def form_valid(self, form):
        evento = get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])
        form.instance.evento = evento
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('eventos:admin_detalle', kwargs={
            'slug_academia': self.request.tenant.slug, 
            'evento_slug': self.kwargs['evento_slug']
        })


class AgregarCodigoDescuentoView(LoginRequiredMixin, CreateView):
    model = CodigoDescuento
    form_class = CodigoDescuentoForm

    def form_valid(self, form):
        evento = get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])
        form.instance.evento = evento
        form.instance.nombre_codigo = form.instance.nombre_codigo.upper()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('eventos:admin_detalle', kwargs={
            'slug_academia': self.request.tenant.slug, 
            'evento_slug': self.kwargs['evento_slug']
        })


class RegistrarVentaPuertaView(LoginRequiredMixin, View):
    """Guarda recibos de taquilla manuales marcando origen en puerta y omitiendo QRs."""
    def post(self, request, slug_academia, evento_slug):
        evento = get_object_or_404(Evento, academia=request.tenant, slug=evento_slug)
        form = VentaPuertaForm(request.POST)
        
        if form.is_valid():
            recibo = form.save(commit=False)
            recibo.evento = evento
            recibo.origen = 'PUERTA'
            recibo.revisado_por_admin = True
            recibo.ingresado_puerta = True
            recibo.monto_total = recibo.cantidad_entradas * recibo.precio_unitario_aplicado
            recibo.save()
            
        # 🎯 CORRECCIÓN AQUÍ: Cambiado 'admin_detail' por 'admin_detalle'
        return redirect('eventos:admin_details' if False else 'eventos:admin_detalle', slug_academia=slug_academia, evento_slug=evento_slug)


from django.contrib import messages # Asegúrate de importar messages si no lo tienes arriba

def cambiar_estado_evento(request, slug_academia, evento_slug, nuevo_estado):
    """
    Controla el flujo de vida del evento. 
    (Fase Beta: Cambio de estado manual liberado sin bloqueo de pasarela de pago).
    """
    if not request.user.is_authenticated:
        return redirect('login')
        
    evento = get_object_or_404(Evento, academia=request.tenant, slug=evento_slug)
    suscripcion = request.tenant.suscripcion_saas
    
    # 🚨 FILTRO PREVIO: Validar que su plan SaaS le permita usar eventos
    if not suscripcion.modulo_eventos_activo:
        messages.error(request, "Tu plan actual no incluye el módulo de eventos.")
        return redirect('academias:dashboard', slug_academia=slug_academia)

    # ========================================================================
    # 🚧 MODO BETA: Lógica de cobro de comisiones comentada temporalmente.
    # Se activará cuando se integren pasarelas (ePayco/Wompi).
    # ========================================================================
    # if not request.tenant.tarjeta_respaldo_configurada:
    #     messages.warning(request, "Registra tu tarjeta de respaldo para operar.")
    #     return redirect('eventos:admin_detalle', slug_academia=slug_academia, evento_slug=evento_slug)
    
    # metricas_comision = evento.calcular_estado_comisiones()
    # (Aquí irá la lógica de débito automático a la tarjeta del Tenant en el futuro)
    # ========================================================================

    # Validamos por seguridad que el estado que viene en la URL existe en las opciones del modelo
    estados_validos = [estado[0] for estado in Evento.ESTADOS]
    
    if nuevo_estado in estados_validos:
        evento.estado = nuevo_estado
        # Usamos update_fields para optimizar la escritura en SQL (muy útil para PythonAnywhere)
        evento.save(update_fields=['estado'])
        messages.success(request, f"Estado del evento actualizado a: {evento.get_estado_display()}")
    else:
        messages.error(request, "Estado no válido.")

    return redirect('eventos:admin_detalle', slug_academia=slug_academia, evento_slug=evento_slug)


# apps/eventos/views.py (Continuación)

class RegistroEventoPublicoView(FormView):
    """
    Controla el formulario público de registro e inscripción en línea para los alumnos.
    Soporta eventos de 1 día o eventos multi-días (Congresos).
    """
    template_name = "eventos/public_registro.html"
    form_class = RegistroOnlineEventoForm

    def dispatch(self, request, *args, **kwargs):
        self.academia_obj = get_object_or_404(Academia, slug=self.kwargs['slug_academia'])
        self.evento_obj = get_object_or_404(Evento, academia=self.academia_obj, slug=self.kwargs['evento_slug'])
        
        # ========================================================================
        # 🚧 MODO BETA: Filtro Antifraude COMENTADO TEMPORALMENTE
        # Como la pasarela está en pausa, los eventos no se marcan como "liquidados".
        # Comentamos esto para que no busque 'public_mora_plataforma.html'.
        # ========================================================================
        # if self.evento_obj.estado in ['REGISTRO_PUERTA', 'FINALIZADO']:
        #     if not self.evento_obj.online_liquidado or (self.evento_obj.estado == 'FINALIZADO' and not self.evento_obj.puerta_liquidado):
        #         return render(request, 'eventos/public_mora_plataforma.html', {
        #             'evento': self.evento_obj, 'academia': self.academia_obj
        #         })

        # 🎯 Flujo normal de redirección
        if self.evento_obj.estado == 'FINALIZADO':
            return render(request, 'eventos/public_finalizado.html', {'evento': self.evento_obj, 'academia': self.academia_obj})
        elif self.evento_obj.estado == 'REGISTRO_PUERTA':
            # 👉 AQUÍ ENRUTAMOS CORRECTAMENTE AL AVISO DE TAQUILLA
            return render(request, 'eventos/public_solo_puerta.html', {'evento': self.evento_obj, 'academia': self.academia_obj})
            
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.evento_obj
        context['academia'] = self.academia_obj
        # Pasamos precios al template para el cálculo JS
        context['precio_por_dia'] = float(self.evento_obj.precio_por_dia)
        context['precio_full'] = float(self.evento_obj.precio_preventa)
        return context

    def form_valid(self, form):
        # Validación temporal de pasarela
        medio_seleccionado = self.request.POST.get('medio_pago_seleccionado', 'MANUAL')
        if medio_seleccionado == 'TARJETA_ONLINE':
            from django.contrib import messages
            messages.error(self.request, "Pago con tarjeta en desarrollo. Usa transferencia manual.")
            return self.form_invalid(form)

        recibo = form.save(commit=False)
        recibo.evento = self.evento_obj
        recibo.origen = 'ONLINE'
        recibo.medio_pago = 'TRANSFERENCIA'
        
        # 🎯 1. CAPTURA SEGURA DEL TIPO DE PASE
        # Buscamos 'tipo_pase' en el HTML. Si no viene, asumimos FULL por seguridad para no afectar al cliente.
        tipo_pase = self.request.POST.get('tipo_pase', 'FULL') 

        # 🧠 2. LÓGICA DE PRECIOS Y ASIGNACIÓN DE DÍAS DINÁMICA
        if self.evento_obj.es_multidias and tipo_pase == 'FULL':
            precio_unidad = self.evento_obj.precio_preventa
            dias_a_otorgar = self.evento_obj.cantidad_dias
        else:
            precio_unidad = self.evento_obj.precio_por_dia
            dias_a_otorgar = 1

        # 🎟️ 3. MOTOR DE CUPONES INTELIGENTE (ACTUALIZADO)
        codigo_texto = form.cleaned_data.get('codigo_cupon', '').strip().upper()
        if codigo_texto:
            cupon = CodigoDescuento.objects.filter(evento=self.evento_obj, nombre_codigo=codigo_texto).first()
            if cupon and cupon.es_valido:
                recibo.codigo_descuento_usado = cupon
                
                # Evaluación dinámica Multi-día
                if self.evento_obj.es_multidias:
                    if tipo_pase == 'FULL':
                        precio_unidad = cupon.precio_especial
                    else:
                        # Si compró 1 día, usa precio_especial_dia (si existe), si no, fallback al especial normal
                        precio_unidad = cupon.precio_especial_dia if cupon.precio_especial_dia else cupon.precio_especial
                else:
                    # Evento normal de 1 día
                    precio_unidad = cupon.precio_especial

                cupon.usos_actuales += 1
                cupon.save(update_fields=['usos_actuales'])

        recibo.precio_unitario_aplicado = precio_unidad
        recibo.monto_total = recibo.cantidad_entradas * precio_unidad
        recibo.save()
        form.save_m2m()

        # 🔄 4. CONFIGURAR BOLETAS CON DÍAS (ASISTENCIAS)
        for boleta in recibo.boletas_qr.all():
            boleta.asistencias_permitidas = dias_a_otorgar
            boleta.save(update_fields=['asistencias_permitidas'])

        # 📷 5. GENERACIÓN DE QRs (Se mantiene idéntico)
        boletas_sesion = []
        for i, boleta in enumerate(recibo.boletas_qr.all(), start=1):
            qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
            qr.add_data(str(boleta.codigo_unico))
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
            boletas_sesion.append({
                'numero': i,
                'codigo_unico': str(boleta.codigo_unico),
                'qr_string': f"data:image/png;base64,{img_str}"
            })
        
        self.request.session['boletas_recien_compradas'] = boletas_sesion

        # 🚀 DISPARADOR DE CORREO: Tickets de Evento y QR
        if recibo.comprador_email:
            # Preparamos las boletas para el template del correo
            boletas_correo = []
            for b in boletas_sesion:
                boletas_correo.append({
                    'codigo': b['codigo_unico'],
                    # Usamos una API pública para garantizar que Gmail/Outlook muestren la imagen del QR
                    'qr_url': f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={b['codigo_unico']}"
                })

            enviar_correo_transaccional(
                asunto=f"🎟️ Tus entradas para {self.evento_obj.nombre}",
                template_name="comunicaciones/ticket_evento.html",
                context={
                    'academia': self.academia_obj,
                    'comprador_nombre': recibo.comprador_nombre,
                    'evento': self.evento_obj,
                    'boletas': boletas_correo
                },
                destinatarios=[recibo.comprador_email]
            )
        
        return redirect('eventos:registro_exito', slug_academia=self.academia_obj.slug, recibo_id=recibo.id)
    

class ValidarCuponAPIView(View):
    """API ultra rápida que valida el cupón vía AJAX/Fetch desde el cliente."""
    def get(self, request, slug_academia, evento_slug):
        codigo = request.GET.get('codigo', '').strip().upper()
        evento = get_object_or_404(Evento, academia__slug=slug_academia, slug=evento_slug)
        cupon = CodigoDescuento.objects.filter(evento=evento, nombre_codigo=codigo).first()
        
        if cupon and cupon.es_valido:
            # Determinamos si hay un precio específico de día, si no, igualamos al full
            precio_dia = float(cupon.precio_especial_dia) if cupon.precio_especial_dia else float(cupon.precio_especial)
            return JsonResponse({
                'valido': True,
                'precio_especial_full': float(cupon.precio_especial),
                'precio_especial_dia': precio_dia
            })
        return JsonResponse({'valido': False})
    

class RegistroExitoView(TemplateView):
    """Muestra la confirmación enviando las boletas estándar con sus IDs y URLs físicas listas."""
    template_name = "eventos/public_exito.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        recibo = get_object_or_404(ReciboEvento, id=self.kwargs['recibo_id'], evento__academia__slug=self.kwargs['slug_academia'])
        
        context['recibo'] = recibo
        context['evento'] = recibo.evento
        # Traemos las boletas guardadas en la base de datos con sus URLs de imagen QR listas
        context['boletas'] = recibo.boletas_qr.all().order_by('id')
        return context
    

class ValidarIngresoQRAPIView(LoginRequiredMixin, View):
    """
    Endpoint que procesa el escaneo del QR permitiendo múltiples ingresos 
    según la cantidad de días comprados.
    """
    def post(self, request, slug_academia, evento_slug):
        import json
        try:
            data = json.loads(request.body)
            codigo_uuid = data.get('codigo_unico', '').strip()
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({'status': 'error', 'message': 'Datos inválidos.'}, status=400)

        # 🔒 Seguridad Tenant y Evento
        boleta = EntradaQR.objects.filter(
            codigo_unico=codigo_uuid,
            recibo__evento__slug=evento_slug,
            recibo__evento__academia=request.tenant
        ).select_related('recibo', 'recibo__evento').first()

        if not boleta:
            return JsonResponse({'status': 'error', 'message': '❌ BOLETA NO VÁLIDA.'}, status=404)

        # 🚨 Control de cupos
        if boleta.asistencias_consumidas >= boleta.asistencias_permitidas:
            fecha_local = boleta.fecha_ultimo_ingreso.astimezone(timezone.get_current_timezone())
            return JsonResponse({
                'status': 'fraud',
                'message': f'⚠️ CUPO AGOTADO. Todos los días fueron consumidos.',
                'comprador': boleta.recibo.comprador_nombre
            }, status=200)

        # ✅ Check-In Exitoso: Incrementamos contador
        boleta.asistencias_consumidas += 1
        boleta.fecha_ultimo_ingreso = timezone.now()
        boleta.save(update_fields=['asistencias_consumidas', 'fecha_ultimo_ingreso'])

        # Mensaje personalizado
        dias_restantes = boleta.asistencias_permitidas - boleta.asistencias_consumidas
        mensaje = f'✅ INGRESO AUTORIZADO. {dias_restantes} días pendientes.' if dias_restantes > 0 else '✅ ÚLTIMO DÍA CONSUMIDO.'

        return JsonResponse({
            'status': 'success',
            'message': mensaje,
            'comprador': boleta.recibo.comprador_nombre,
            'recibo': boleta.recibo.numero_recibo,
            'asistencias_consumidas': boleta.asistencias_consumidas
        }, status=200)