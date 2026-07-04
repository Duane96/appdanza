# apps/eventos/views.py
from datetime import timedelta
from django.db import transaction

from django.http import JsonResponse
from django.views.generic import ListView, CreateView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.db.models import Sum, Q

from .models import Evento, CodigoDescuento, FasePreventa, ReciboEvento, GastoEvento, TipoPase
from .forms import EventoForm, CodigoDescuentoForm, FasePreventaForm, GastoEventoForm, TipoPaseForm, VentaPuertaForm

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

from django.db.models import Sum, DecimalField
from django.db.models.functions import Coalesce

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
        # Instanciamos el formulario en limpio para que el modal de creación renderice los widgets correctos
        context['form'] = EventoForm() 
        return context


class EventoCreateView(LoginRequiredMixin, CreateView):
    model = Evento
    form_class = EventoForm
    template_name = "eventos/admin_list.html" 

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 🚀 FIX SENIOR: Inyectamos la lista de eventos para que la pantalla de fondo no desaparezca si el formulario falla.
        context['eventos'] = Evento.objects.filter(academia=self.request.tenant)
        context['form'] = self.get_form()
        return context

    def form_valid(self, form):
        evento = form.save(commit=False)
        evento.academia = self.request.tenant
        
        base_slug = slugify(evento.nombre)
        evento.slug = base_slug
        
        if Evento.objects.filter(academia=self.request.tenant, slug=base_slug).exists():
            form.add_error('nombre', 'Ya cuentas con un evento activo registrado con este nombre.')
            return self.form_invalid(form)
            
        evento.save()
        form.save_m2m()

        # 🚀 LÓGICA SENIOR: AUTO-GENERACIÓN DE PASES BASE
        from .models import TipoPase
        if evento.es_multidias:
            TipoPase.objects.create(evento=evento, nombre="Full Pass", precio=0, accesos_permitidos=3)
            TipoPase.objects.create(evento=evento, nombre="Pase 1 Día", precio=0, accesos_permitidos=1)
        else:
            TipoPase.objects.create(evento=evento, nombre="Entrada General", precio=0, accesos_permitidos=1)

        # Inyectamos el mensaje de éxito para que aparezca arriba de la lista
        messages.success(self.request, f"¡El evento '{evento.nombre}' se ha creado exitosamente!")

        # 🎯 FIX DEFINITIVO: Redirigimos usando el nombre exacto de tu URL ('admin_lista')
        return redirect('eventos:admin_lista', slug_academia=self.request.tenant.slug)


class EventoUpdateView(LoginRequiredMixin, UpdateView):
    """Vista para editar un evento existente garantizando aislamiento estricto y configuración de Pases."""
    model = Evento
    form_class = EventoForm
    template_name = "eventos/admin_form.html" 

    def get_object(self):
        # Filtro estricto Multi-Tenant
        return get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Inyectamos los formularios para Pases y Fases
        # (Asegúrate de importar TipoPaseForm al inicio del archivo)
        from .forms import TipoPaseForm 
        context['form_pase'] = TipoPaseForm()
        
        # Enviamos los pases y fases ya creados al template para mostrarlos en tablas
        context['pases_creados'] = self.object.pases_personalizados.all()
        context['fases_creadas'] = self.object.fases_preventa.all().order_by('fecha_limite')
        return context

    def form_valid(self, form):
        evento = form.save(commit=False)
        evento.academia = self.request.tenant 
        
        base_slug = slugify(evento.nombre)
        evento.slug = base_slug
        
        if Evento.objects.filter(academia=self.request.tenant, slug=base_slug).exclude(pk=evento.pk).exists():
            form.add_error('nombre', 'Ya existe OTRO evento con este nombre en tu calendario.')
            return self.form_invalid(form)
            
        evento.save()
        return redirect(self.get_success_url())

    def get_success_url(self):
        # Redirige de vuelta a la misma vista de edición para que la experiencia sea continua
        return reverse('eventos:admin_editar', kwargs={
            'slug_academia': self.request.tenant.slug,
            'evento_slug': self.object.slug
        })
    

class AgregarTipoPaseView(LoginRequiredMixin, CreateView):
    """Guarda un pase a la carta desde la vista de edición."""
    model = TipoPase
    form_class = TipoPaseForm

    def form_valid(self, form):
        evento = get_object_or_404(Evento, academia=self.request.tenant, slug=self.kwargs['evento_slug'])
        
        # 🚀 BLINDAJE SENIOR: Si no es multidías, forzamos a 1 día de acceso.
        if not evento.es_multidias:
            form.instance.accesos_permitidos = 1
            
        # 🚀 FIX DE INTEGRIDAD DB: Si usan preventas o el precio viene nulo, lo forzamos a 0.
        if evento.tiene_fases_fechas or form.instance.precio is None:
            form.instance.precio = 0
            
        form.instance.evento = evento
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('eventos:admin_editar', kwargs={
            'slug_academia': self.request.tenant.slug, 
            'evento_slug': self.kwargs['evento_slug']
        }) + "#pases"


class AgregarFasePreventaView(LoginRequiredMixin, View):
    """
    Vista Senior: Guarda la cáscara de la fase y construye 
    la Matriz de Precios dinámicamente con Auto-Curación.
    """
    def post(self, request, slug_academia, evento_slug):
        # 1. Seguridad Multi-tenant y obtención del evento
        evento = get_object_or_404(Evento, academia=request.tenant, slug=evento_slug)
        
        # 🚀 AUTO-CORRECCIÓN SENIOR: Si olvidaron guardar el Tab 1, prendemos el switch a la fuerza
        if not evento.tiene_fases_fechas:
            evento.tiene_fases_fechas = True
            evento.save(update_fields=['tiene_fases_fechas'])
        
        # 2. Captura de datos básicos de la Fase
        nombre_fase = request.POST.get('nombre_fase')
        fecha_limite = request.POST.get('fecha_limite')
        
        # Precios clásicos (llegarán vacíos si están usando la lógica de Pases a la Carta)
        precio_full = request.POST.get('precio_full') or None
        precio_dia = request.POST.get('precio_dia') or None

        # 3. Guardamos la Fase en la base de datos
        from .models import FasePreventa
        fase = FasePreventa.objects.create(
            evento=evento,
            nombre_fase=nombre_fase,
            fecha_limite=fecha_limite,
            precio_full=precio_full,
            precio_dia=precio_dia
        )

        # 🧠 4. LÓGICA DE LA MATRIZ: Interceptar precios de Pases a la Carta
        from .models import PrecioFasePase, TipoPase
        pases_activos = TipoPase.objects.filter(evento=evento)
        
        for pase in pases_activos:
            precio_input = request.POST.get(f'precio_pase_{pase.id}')
            if precio_input:
                PrecioFasePase.objects.create(
                    fase=fase,
                    pase=pase,
                    precio=precio_input
                )
        
        from django.contrib import messages
        messages.success(request, f"Fase '{nombre_fase}' añadida correctamente al cronograma.")
        
        # 5. Redireccionamos a la vista de edición
        return redirect(reverse('eventos:admin_editar', kwargs={
            'slug_academia': request.tenant.slug, 
            'evento_slug': evento.slug
        }) + "#fases")



class EditarTipoPaseView(LoginRequiredMixin, UpdateView):
    """Edita el precio, nombre o accesos de un pase específico."""
    model = TipoPase
    form_class = TipoPaseForm
    
    def get_queryset(self):
        return TipoPase.objects.filter(evento__academia=self.request.tenant)

    def form_valid(self, form):
        # 🚀 BLINDAJE SENIOR: Protegemos la edición también
        if not form.instance.evento.es_multidias:
            form.instance.accesos_permitidos = 1
            
        # 🚀 FIX DE INTEGRIDAD DB: Evitar error NOT NULL al editar
        if form.instance.evento.tiene_fases_fechas or form.instance.precio is None:
            form.instance.precio = 0
            
        messages.success(self.request, f"Pase '{form.instance.nombre}' actualizado correctamente.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('eventos:admin_editar', kwargs={
            'slug_academia': self.request.tenant.slug, 
            'evento_slug': self.object.evento.slug
        }) + "#pases"

class EliminarTipoPaseView(LoginRequiredMixin, View):
    """Elimina un pase específico de la base de datos."""
    def post(self, request, slug_academia, pk):
        pase = get_object_or_404(TipoPase, id=pk, evento__academia=request.tenant)
        evento_slug = pase.evento.slug
        nombre_pase = pase.nombre
        
        # Opcional: Validar si el pase ya tiene ventas antes de borrarlo (Buenas prácticas)
        if pase.recibos.exists():
            messages.error(request, f"No puedes eliminar el pase '{nombre_pase}' porque ya tiene ventas registradas.")
        else:
            pase.delete()
            messages.success(request, f"Pase '{nombre_pase}' eliminado correctamente.")
            
        return redirect(reverse('eventos:admin_editar', kwargs={
            'slug_academia': request.tenant.slug, 
            'evento_slug': evento_slug
        }) + "#pases")
    







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
        # Usamos Coalesce para que PostgreSQL/SQLite devuelva un Decimal(0.00) nativo si no hay registros.
        # Esto blinda las operaciones matemáticas y la memoria en PythonAnywhere.
        
        context['total_entradas_vendidas'] = ReciboEvento.objects.filter(evento=evento, anulado=False).aggregate(
            total=Coalesce(Sum('cantidad_entradas'), 0)
        )['total']
        
        context['dinero_efectivo'] = ReciboEvento.objects.filter(evento=evento, medio_pago='EFECTIVO', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        
        context['dinero_transferencia'] = ReciboEvento.objects.filter(evento=evento, medio_pago='TRANSFERENCIA', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        
        context['dinero_tarjeta'] = ReciboEvento.objects.filter(evento=evento, medio_pago='TARJETA', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        
        dinero_online = ReciboEvento.objects.filter(evento=evento, origen='ONLINE', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        context['dinero_online'] = dinero_online
        
        # Total global recolectado de forma física en la Taquilla de Puerta
        dinero_en_puerta = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        context['dinero_en_puerta'] = dinero_en_puerta
        
        # Ingresos totales brutos del evento (Online + Puerta)
        ingresos_totales = ReciboEvento.objects.filter(evento=evento, anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        context['ingresos_totales'] = ingresos_totales

        # 🎯 3. DESGLOSE ESPECÍFICO DE DINERO ADQUIRIDO EN TAQUILLA (PUERTA)
        context['puerta_efectivo'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='EFECTIVO', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        
        context['puerta_transferencia'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='TRANSFERENCIA', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']
        
        context['puerta_tarjeta'] = ReciboEvento.objects.filter(evento=evento, origen='PUERTA', medio_pago='TARJETA', anulado=False).aggregate(
            total=Coalesce(Sum('monto_total'), 0, output_field=DecimalField())
        )['total']

        # 🔴 4. REPORTE DE EGRESOS E INVERSIONES DEL EVENTO
        gastos = GastoEvento.objects.filter(evento=evento).order_by('-id')
        context['gastos'] = gastos
        gastos_totales = gastos.aggregate(total=Coalesce(Sum('monto'), 0, output_field=DecimalField()))['total']
        context['gastos_totales'] = gastos_totales

        # 📈 5. BALANCE NETO DE OPERACIÓN DE LA ACADEMIA
        # Como todo es un Decimal asegurado, la resta jamás fallará
        context['balance_neto'] = ingresos_totales - gastos_totales

        # 📥 6. CONTADOR DE ASISTENCIA REAL MEDIANTE LOG DE ACCESOS
        # Sumamos los registros que ya cruzaron la puerta escaneando su QR online
        # ✅ CORRECCIÓN: Filtramos usando los campos reales de la BD
        total_ingresos_qr = EntradaQR.objects.filter(
            recibo__evento=evento,
            recibo__anulado=False, 
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

        # Agrega esta línea justo adentro del final de get_context_data, antes del 'return context':
        context['form_pase'] = TipoPaseForm()

        # 🚀 9. NUEVO: MÉTRICAS AVANZADAS POR TIPO DE PASE Y FASE
        from django.db.models import Count
        
        # Cuántas entradas y cuánta plata ha generado cada pase a la carta
        if evento.tiene_pases_personalizados:
            pases_metricas = TipoPase.objects.filter(evento=evento).annotate(
                total_vendidos=Coalesce(Sum('recibos__cantidad_entradas'), 0),
                total_recaudado=Coalesce(Sum('recibos__monto_total'), 0, output_field=DecimalField())
            )
            context['metricas_pases'] = pases_metricas

        # Cuánta plata se movió en cada fase de preventa (Para saber qué fase fue más exitosa)
        if evento.tiene_fases_fechas:
            fases_metricas = FasePreventa.objects.filter(evento=evento).annotate(
                total_recaudado=Coalesce(Sum('recibos__monto_total'), 0, output_field=DecimalField())
            )
            context['metricas_fases'] = fases_metricas

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
    """
    Vista Senior: Guarda recibos manuales y enruta el dinero y los QRs 
    dependiendo de la fase de vida del evento.
    """
    def post(self, request, slug_academia, evento_slug):
        evento = get_object_or_404(Evento, academia=request.tenant, slug=evento_slug)
        form = VentaPuertaForm(request.POST)
        
        if form.is_valid():
            recibo = form.save(commit=False)
            recibo.evento = evento
            recibo.revisado_por_admin = True
            # Calculamos el costo total
            recibo.monto_total = recibo.cantidad_entradas * recibo.precio_unitario_aplicado
            
            # 🧠 LÓGICA SENIOR: Dinamismo según el estado actual del evento
            if evento.estado == 'REGISTRO_ONLINE':
                # Es una venta manual anticipada (Ej. Transferencia vía WhatsApp)
                recibo.origen = 'ONLINE'
                recibo.ingresado_puerta = False
                recibo.save() # Al guardar con origen='ONLINE', el modelo auto-genera los QRs
                
                # 🔄 Configurar las asistencias a las boletas recién creadas
                dias_a_otorgar = evento.cantidad_dias if evento.es_multidias else 1
                for boleta in recibo.boletas_qr.all():
                    boleta.asistencias_permitidas = dias_a_otorgar
                    boleta.save(update_fields=['asistencias_permitidas'])
            else:
                # El evento ya empezó, es venta física en la taquilla del lugar
                recibo.origen = 'PUERTA'
                recibo.ingresado_puerta = True
                recibo.save()
            
        return redirect('eventos:admin_detalle', slug_academia=slug_academia, evento_slug=evento_slug)


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
    Lógica Senior: Detecta fases de preventa y blinda contra dobles envíos concurrentes (Idempotencia).
    """
    template_name = "eventos/public_registro.html"
    form_class = RegistroOnlineEventoForm

    def dispatch(self, request, *args, **kwargs):
        # Aislamiento estricto del Tenant (Academia) y del evento específico
        self.academia_obj = get_object_or_404(Academia, slug=self.kwargs['slug_academia'])
        self.evento_obj = get_object_or_404(Evento, academia=self.academia_obj, slug=self.kwargs['evento_slug'])
        
        # Validación del ciclo de vida del evento
        if self.evento_obj.estado == 'FINALIZADO':
            return render(request, 'eventos/public_finalizado.html', {'evento': self.evento_obj, 'academia': self.academia_obj})
        elif self.evento_obj.estado == 'REGISTRO_PUERTA':
            return render(request, 'eventos/public_solo_puerta.html', {'evento': self.evento_obj, 'academia': self.academia_obj})
            
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['evento'] = self.evento_obj
        context['academia'] = self.academia_obj
        
        # 🕒 1. BUSCAR LA FASE ACTIVA EN EL CRONOGRAMA
        fase_activa = None
        if self.evento_obj.fases_preventa.exists():
            fase_activa = self.evento_obj.fases_preventa.filter(fecha_limite__gte=timezone.now()).order_by('fecha_limite').first()
            if not fase_activa:
                fase_activa = self.evento_obj.fases_preventa.order_by('-fecha_limite').first()
                context['fase_vencida'] = True
        
        context['fase_activa'] = fase_activa

        # 🎟️ 2. PREPARAR MATRIZ DE PRECIOS DE LOS PASES (ESTRUCTURA PLANA ANTI-FALLOS)
        pases_data = []
        for pase in self.evento_obj.pases_personalizados.all():
            precio_final = pase.precio
            
            if fase_activa: 
                pivote = fase_activa.precios_pases.filter(pase=pase).first()
                if pivote and pivote.precio is not None:
                    precio_final = pivote.precio
            
            # Diccionario plano para que el HTML lo consuma sin hacer consultas adicionales a la BD
            pases_data.append({
                'id': pase.id,
                'nombre': pase.nombre,
                'accesos_permitidos': pase.accesos_permitidos,
                'precio_actual': float(precio_final or 0)
            })
                
        context['pases_disponibles'] = pases_data
        context['precio_por_dia'] = float(self.evento_obj.precio_por_dia or 0)
        context['precio_full'] = float(self.evento_obj.precio_preventa or 0)
        return context
    
    @transaction.atomic
    def form_valid(self, form):
        # 🚀 1. BLINDAJE SENIOR BACKEND (IDEMPOTENCIA ANTI-DOBLE CLIC / LAG DE RED):
        # Evitamos peticiones concurrentes buscando si la misma persona
        # ya generó un recibo exitoso para ESTE evento en una ventana de 2 minutos.
        tiempo_limite = timezone.now() - timedelta(minutes=2)
        
        recibo_reciente = ReciboEvento.objects.filter(
            evento=self.evento_obj,
            anulado=False,
            fecha__gte=tiempo_limite
        ).filter(
            # Coincidencia por correo O por teléfono para detectar al usuario
            Q(comprador_correo__iexact=form.cleaned_data.get('comprador_correo')) |
            Q(comprador_telefono=form.cleaned_data.get('comprador_telefono'))
        ).first()

        # Si ya existe un registro reciente, asumimos que fue doble clic o reintento automático del navegador.
        # No gastamos CPU de PythonAnywhere procesando imágenes o QRs, solo lo llevamos al éxito original.
        if recibo_reciente:
            return redirect('eventos:registro_exito', slug_academia=self.academia_obj.slug, recibo_id=recibo_reciente.id)

        # =========================================================================
        # 🟢 A PARTIR DE AQUÍ SIGUE LA LÓGICA ESTÁNDAR DE CREACIÓN (Sin riesgos)
        # =========================================================================
        medio_seleccionado = self.request.POST.get('medio_pago_seleccionado', 'MANUAL')
        if medio_seleccionado == 'TARJETA_ONLINE':
            from django.contrib import messages
            messages.error(self.request, "Pago con tarjeta en desarrollo. Usa transferencia manual.")
            return self.form_invalid(form)

        recibo = form.save(commit=False)
        recibo.evento = self.evento_obj
        recibo.origen = 'ONLINE'
        recibo.medio_pago = 'TRANSFERENCIA'
        
        tipo_pase_input = self.request.POST.get('tipo_pase', 'FULL') 
        pase_personalizado = None
        tipo_pase_cupon = 'FULL' 
        
        # 🛡️ Aplicamos la misma búsqueda de fase al procesar el pago
        fase_activa = None
        if self.evento_obj.fases_preventa.exists():
            fase_activa = self.evento_obj.fases_preventa.filter(fecha_limite__gte=timezone.now()).order_by('fecha_limite').first()
            if not fase_activa:
                fase_activa = self.evento_obj.fases_preventa.order_by('-fecha_limite').first()

        if tipo_pase_input.startswith('PASE_'):
            pase_id = tipo_pase_input.split('_')[1]
            from .models import TipoPase 
            pase_personalizado = TipoPase.objects.filter(id=pase_id, evento=self.evento_obj).first()

        # 🧠 2. ASIGNACIÓN DE PRECIO DESDE LA MATRIZ PIVOTE
        if pase_personalizado:
            if fase_activa:
                pivote = fase_activa.precios_pases.filter(pase=pase_personalizado).first()
                precio_unidad = pivote.precio if pivote else (pase_personalizado.precio or 0)
            else:
                precio_unidad = pase_personalizado.precio or 0
                
            dias_a_otorgar = pase_personalizado.accesos_permitidos
            tipo_pase_cupon = 'FULL' if dias_a_otorgar > 1 else 'DIA'
            
        elif not self.evento_obj.es_multidias:
            precio_unidad = self.evento_obj.precio_preventa
            dias_a_otorgar = 1
            tipo_pase_cupon = 'FULL'
        elif self.evento_obj.es_multidias and tipo_pase_input == 'FULL':
            precio_unidad = self.evento_obj.precio_preventa
            dias_a_otorgar = self.evento_obj.cantidad_dias
            tipo_pase_cupon = 'FULL'
        else:
            precio_unidad = self.evento_obj.precio_por_dia
            dias_a_otorgar = 1
            tipo_pase_cupon = 'DIA'

        # 🎟️ 3. MOTOR DE CUPONES INTELIGENTE
        codigo_texto = form.cleaned_data.get('codigo_cupon', '').strip().upper()
        if codigo_texto:
            cupon = CodigoDescuento.objects.filter(evento=self.evento_obj, nombre_codigo=codigo_texto).first()
            if cupon and cupon.es_valido:
                recibo.codigo_descuento_usado = cupon
                
                if tipo_pase_cupon == 'FULL':
                    precio_unidad = cupon.precio_especial
                else:
                    precio_unidad = cupon.precio_especial_dia if cupon.precio_especial_dia else cupon.precio_especial

                cupon.usos_actuales += 1
                cupon.save(update_fields=['usos_actuales'])

        recibo.precio_unitario_aplicado = precio_unidad
        recibo.monto_total = recibo.cantidad_entradas * precio_unidad
        recibo.tipo_pase = pase_personalizado
        recibo.fase_preventa = fase_activa
        recibo.save()
        form.save_m2m()

        # 🔄 4. CONFIGURAR DÍAS DE ASISTENCIA A LAS BOLETAS QR
        for boleta in recibo.boletas_qr.all():
            boleta.asistencias_permitidas = dias_a_otorgar
            boleta.save(update_fields=['asistencias_permitidas'])

        # 📷 5. GENERACIÓN DE QRs EN MEMORIA RAM (Sin abusar del disco del servidor)
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

        # 🚀 6. DISPARADOR DE CORREO TRANSACCIONAL ASÍNCRONO
        if recibo.comprador_correo:
            boletas_correo = []
            for b in boletas_sesion:
                boletas_correo.append({
                    'codigo': b['codigo_unico'],
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
                destinatarios=[recibo.comprador_correo]
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

        if boleta.recibo.anulado:
            return JsonResponse({
                'status': 'fraud', 
                'message': '❌ RECIBO ANULADO. ACCESO DENEGADO.',
                'comprador': boleta.recibo.comprador_nombre
            }, status=200)

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
    


class AnularReciboView(LoginRequiredMixin, View):
    """Anula un recibo y bloquea el acceso de todas sus boletas asociadas."""
    def post(self, request, slug_academia, evento_slug, recibo_id):
        recibo = get_object_or_404(ReciboEvento, id=recibo_id, evento__academia=request.tenant, evento__slug=evento_slug)
        
        # Anulamos el recibo
        recibo.anulado = True
        recibo.save(update_fields=['anulado'])
        
        messages.success(request, f"El recibo #{recibo.numero_recibo} y sus entradas han sido anulados correctamente.")
        return redirect('eventos:admin_detalle', slug_academia=slug_academia, evento_slug=evento_slug)
    

    # apps/eventos/views.py

class EditarFasePreventaView(LoginRequiredMixin, View):
    """
    Vista Senior: Actualiza la fecha, nombre y todos los precios de la matriz
    asociados a una Fase de Preventa específica.
    """
    def post(self, request, slug_academia, pk):
        from .models import FasePreventa, PrecioFasePase
        
        # 1. Filtro estricto Multi-Tenant
        fase = get_object_or_404(FasePreventa, id=pk, evento__academia=request.tenant)
        evento = fase.evento

        # 2. Actualizamos datos principales de la fase
        fase.nombre_fase = request.POST.get('nombre_fase', fase.nombre_fase)
        
        fecha_limite = request.POST.get('fecha_limite')
        if fecha_limite:
            fase.fecha_limite = fecha_limite
            
        fase.save(update_fields=['nombre_fase', 'fecha_limite'])

        # 3. 🧠 RE-CÁLCULO DE LA MATRIZ DE PRECIOS
        # Recorremos los pases enviados en el POST y actualizamos la tabla pivote
        for pivote in fase.precios_pases.all():
            precio_input = request.POST.get(f'precio_pase_{pivote.pase.id}')
            if precio_input is not None and precio_input != '':
                pivote.precio = precio_input
                pivote.save(update_fields=['precio'])

        messages.success(request, f"Preventa '{fase.nombre_fase}' actualizada correctamente.")
        
        return redirect(reverse('eventos:admin_editar', kwargs={
            'slug_academia': slug_academia, 
            'evento_slug': evento.slug
        }) + "#fases")


class EliminarFasePreventaView(LoginRequiredMixin, View):
    """Vista Senior: Elimina una Fase de Preventa en cascada (borra su matriz de precios)."""
    def post(self, request, slug_academia, pk):
        from .models import FasePreventa
        
        fase = get_object_or_404(FasePreventa, id=pk, evento__academia=request.tenant)
        evento_slug = fase.evento.slug
        nombre_fase = fase.nombre_fase
        
        # Opcional: Podrías validar si ya se vendieron boletas en esta fase, pero 
        # como la fase solo dicta el precio, borrarla no afecta recibos viejos.
        fase.delete()
        
        messages.success(request, f"Preventa '{nombre_fase}' eliminada del cronograma.")
        
        return redirect(reverse('eventos:admin_editar', kwargs={
            'slug_academia': slug_academia, 
            'evento_slug': evento_slug
        }) + "#fases")