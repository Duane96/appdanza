import csv

from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from apps.academias.models import Academia, PerfilUsuario
from django.core.mail import send_mail
from django.conf import settings
from .forms import ConfigPagoSaaSForm
from .models import PlanSaaS, SuscripcionAcademia

from django.shortcuts import get_object_or_404, render
from django.views import View
from django.http import HttpResponse, JsonResponse
from .models import *

from django.shortcuts import redirect
from django.urls import reverse
from apps.planes_estudiantes.models import Estudiante
from .models import PlanSaaS, SuscripcionAcademia
from django.utils import timezone

from django.db import transaction

from django.contrib.auth.models import User

from apps.eventos.models import Evento  # 🚨 NUEVO IMPORT
from django.utils import timezone       # 🚨 NUEVO IMPORT


from apps.comunicaciones.services import enviar_correo_transaccional

from django.db.models import Q, Count

from apps.finanzas.models import ReciboIngreso, Gasto

from django.db.models import Sum
from django.contrib import messages
import json

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import io

from .forms import *
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from django.contrib.messages.views import SuccessMessageMixin

from django.db.models import Min
from django.db.models.functions import Coalesce


def api_finanzas_academia(request):
    academia_id = request.GET.get('academia_id')
    
    # Optimizamos: traemos el conteo y sumatorias por evento en una sola consulta
    eventos_data = Evento.objects.filter(academia_id=academia_id).annotate(
        cant_recibos=Count('recibos_evento'),
        total_gastos_evento=Sum('gastos_evento__monto'),
        ingresos_online=Sum('recibos_evento__monto_total', filter=Q(recibos_evento__origen='ONLINE')),
        ingresos_taquilla=Sum('recibos_evento__monto_total', filter=Q(recibos_evento__origen='PUERTA'))
    ).values(
        'nombre', 'cant_recibos', 'ingresos_online', 'ingresos_taquilla', 'total_gastos_evento'
    )

    # Convertimos los QuerySets a una lista de diccionarios con cálculo seguro
    lista_eventos = []
    for e in eventos_data:
        onl = float(e['ingresos_online'] or 0)
        taq = float(e['ingresos_taquilla'] or 0)
        gast = float(e['total_gastos_evento'] or 0)
        lista_eventos.append({
            'nombre': e['nombre'],
            'cant_recibos': e['cant_recibos'],
            'ingresos_online': onl,
            'ingresos_taquilla': taq,
            'gastos': gast,
            'total_ingreso': onl + taq, # ✅ Django hace la suma real
            'neto': (onl + taq) - gast   # ✅ Django calcula el neto real
        })

    # 2. Resumen: Ingresos Totales y Gastos
    # Separamos ingresos de tienda para que puedas mostrarlos aparte
    # 1. Filtros base
    ingresos = ReciboIngreso.objects.filter(academia_id=academia_id, estado='ACTIVO')
    
    # 2. Desglose real
    total_ingresos = ingresos.aggregate(Sum('monto'))['monto__sum'] or 0
    ingresos_tienda = ingresos.filter(tipo_ingreso='TIENDA').aggregate(Sum('monto'))['monto__sum'] or 0
    
    # Ingreso por Membresías: Total menos lo que vino de tienda
    ingresos_membresias = total_ingresos - ingresos_tienda
    
    total_gastos = Gasto.objects.filter(academia_id=academia_id, estado='ACTIVO').aggregate(Sum('monto'))['monto__sum'] or 0
    estudiantes_activos = Estudiante.unfiltered_objects.filter(academia_id=academia_id, estado='ACTIVO').count()
    
    # 3. Ticket Promedio Lógico: Ingresos de membresías / Estudiantes activos
    ticket_promedio = ingresos_membresias / estudiantes_activos if estudiantes_activos > 0 else 0

    return JsonResponse({
        'status': 'success',
        'eventos': lista_eventos,
        'resumen': {
            'ingresos_totales': float(total_ingresos),
            'ingresos_tienda': float(ingresos_tienda),
            'gastos': float(total_gastos),
            'balance': float(total_ingresos - total_gastos),
            'margen': (float(total_ingresos - total_gastos) / float(total_ingresos) * 100) if total_ingresos > 0 else 0,
            'estudiantes_activos': estudiantes_activos,
            'ticket_promedio': float(ticket_promedio) # Ahora es limpio
        }
    })

class PanelMaestroDashboardView(UserPassesTestMixin, TemplateView):
    """Centro de mando global para el dueño del SaaS (Súper Admin)."""
    template_name = "saas_core/master_dashboard.html"

    def test_func(self):
        """Filtro de seguridad estricto: Solo superusuarios reales."""
        return self.request.user.is_superuser and self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 🎯 REPARACIÓN SENIOR: KPIs Globales usando 'unfiltered_objects'
        context['total_academias'] = Academia.unfiltered_objects.count()
        context['academias_activas'] = SuscripcionAcademia.objects.filter(estado='ACTIVO').count()
        context['academias_suspendidas'] = SuscripcionAcademia.objects.filter(estado='SUSPENDIDO').count()
        
        # 📊 NUEVOS KPIs: Estudiantes y Eventos totales del ecosistema
        context['total_estudiantes'] = Estudiante.unfiltered_objects.count()
        context['total_eventos'] = Evento.unfiltered_objects.count()
        # Nota: Si ya tienes el modelo de Tienda/Ventas, cámbialo aquí. Dejo un placeholder.
        context['total_tienda'] = 0 
        
        # 🚀 OPTIMIZACIÓN EXTREMA: Traemos academias, planes y contamos sus alumnos/eventos en 1 sola Query
        context['academias'] = Academia.unfiltered_objects.all().select_related(
            'suscripcion_saas__plan'
        ).annotate(
            # 'estudiantes' y 'eventos_academia' son los related_name de tus modelos
            num_estudiantes=Count('estudiantes', distinct=True),
            num_eventos=Count('eventos_academia', distinct=True)
        ).order_by('-fecha_creacion')
        
        context['planes_saas'] = PlanSaaS.objects.all()
        context['config'] = LandingPageConfig.objects.first() or LandingPageConfig()
        context['form_pago_global'] = ConfigPagoSaaSForm(instance=ConfigPagoGlobalSaaS.objects.first())
        
        return context
    
# apps/saas_core/views.py

class CrearAcademiaSaaSView(UserPassesTestMixin, View):
    """Crea la entidad de la academia. Nace SUSPENDIDA y sin asignar un plan específico."""
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        nombre = request.POST.get('nombre')
        slug = request.POST.get('slug')
        template_personalizado = request.POST.get('template_landing_personalizado', '').strip() or None
        es_productora = request.POST.get('es_solo_eventos') == 'on'
        admin_email = request.POST.get('admin_email')
        admin_password = request.POST.get('admin_password')

        with transaction.atomic():
            # 1. Creamos la escuela de baile
            nueva_academia = Academia.unfiltered_objects.create(
                nombre=nombre,
                slug=slug,
                template_landing_personalizado=template_personalizado,
                es_solo_eventos=es_productora,
                activo=True
            )

            # 🚀 LÓGICA DE PLAN POR DEFECTO: 
            # Como el modelo exige un plan, le asignamos el primero que exista en la BD.
            # (El cliente no lo podrá usar de todas formas porque nace SUSPENDIDO).
            plan_inicial = PlanSaaS.objects.first()
            
            # 🛡️ Fallback por si la BD de planes está vacía:
            if not plan_inicial:
                plan_inicial = PlanSaaS.objects.create(
                    nombre="Plan Base (Autogenerado)",
                    precio_mensual=0,
                    max_estudiantes=0
                )

            fecha_hoy = timezone.now().date()
            
            # Creamos la suscripción en estado SUSPENDIDO
            SuscripcionAcademia.objects.create(
                academia=nueva_academia,
                plan=plan_inicial,
                estado='SUSPENDIDO', 
                ya_uso_prueba_gratis=True, 
                dias_regalados_prueba=0,
                fecha_inicio=fecha_hoy,
                fecha_vencimiento=fecha_hoy, 
                es_cuenta_partner_gratis=False
            )

            # 2. Credenciales de acceso
            nuevo_admin = User.objects.create_user(
                username=admin_email,
                email=admin_email,
                password=admin_password
            )
            nuevo_admin.is_staff = False 
            nuevo_admin.save()

            PerfilUsuario.objects.create(
                user=nuevo_admin,
                academia=nueva_academia,
                rol='ADMIN_ACADEMIA'
            )

            # 3. Disparador de correo
            enviar_correo_transaccional(
                asunto=f"¡Bienvenido a AppDanza, {nueva_academia.nombre}!",
                template_name="comunicaciones/bienvenida_academia.html",
                context={'academia': nueva_academia},
                destinatarios=[admin_email]
            )

        messages.success(request, f"Academia {nombre} creada. Esperando validación de pago o asignación de Plan.")
        return redirect('saas_core:panel_maestro_dashboard')

class MasterAsignarYRenovarPlanView(UserPassesTestMixin, View):
    """
    Vista Súper Admin: Asigna un plan nuevo o renueva uno existente.
    Si la academia es Partner, no genera cobro. Si no, genera el ReciboSaaS.
    """
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        plan_id = request.POST.get('plan_id')
        meses_a_renovar = int(request.POST.get('meses_a_renovar', 1))
        
        academia = get_object_or_404(Academia.unfiltered_objects, id=academia_id)
        plan = get_object_or_404(PlanSaaS, id=plan_id)
        hoy = timezone.localtime(timezone.now()).date()

        with transaction.atomic():
            # 1. Buscar si ya existe una suscripción, si no, crearla
            suscripcion, created = SuscripcionAcademia.objects.get_or_create(
                academia=academia,
                defaults={
                    'plan': plan,
                    'estado': 'ACTIVO',
                    'fecha_inicio': hoy,
                    'fecha_vencimiento': hoy + timezone.timedelta(days=30 * meses_a_renovar)
                }
            )

            # 2. Lógica de Actualización y Fechas (Si la suscripción ya existía)
            if not created:
                suscripcion.plan = plan
                suscripcion.estado = 'ACTIVO'
                
                # Si está vencida, partimos de hoy. Si no, sumamos desde la fecha de vencimiento actual.
                base_fecha = suscripcion.fecha_vencimiento if suscripcion.fecha_vencimiento >= hoy else hoy
                suscripcion.fecha_vencimiento = base_fecha + timezone.timedelta(days=30 * meses_a_renovar)
                suscripcion.save()

            # 3. 🚀 GENERACIÓN DEL RECIBO (Si NO es cuenta Partner)
            # Solo generamos deuda (recibo) si la cuenta no es VIP gratis
            if not suscripcion.es_cuenta_partner_gratis:
                monto_calculado = plan.precio_mensual * meses_a_renovar
                
                # Creamos el registro en tus Finanzas Master
                ReciboSaaS.objects.create(
                    academia=academia,
                    plan=plan,
                    monto=monto_calculado,
                    concepto=f"Asignación/Renovación: Plan {plan.nombre} ({meses_a_renovar} mes/es).",
                    medio_pago="PENDIENTE / POR VALIDAR" # Puedes cambiar esto si es pago directo
                )
                
            messages.success(request, f"¡Suscripción de {academia.nombre} actualizada correctamente!")
            return redirect('saas_core:panel_maestro_dashboard')


# apps/saas_core/views.py

class CrearPlanSaaSView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        nombre = request.POST.get('nombre')
        precio = request.POST.get('precio')
        max_estudiantes = request.POST.get('max_estudiantes')
        
        # Evaluamos listas de valores positivos por seguridad ('on', 'True', 'true', '1')
        PlanSaaS.objects.create(
            nombre=nombre,
            precio_mensual=precio,
            max_estudiantes=max_estudiantes,
            permite_estudiantes=request.POST.get('estudiantes') in ['on', 'True', 'true', '1'],
            permite_multimedia=request.POST.get('multimedia') in ['on', 'True', 'true', '1'],
            permite_finanzas=request.POST.get('finanzas') in ['on', 'True', 'true', '1'],
            permite_asistencias_qr=request.POST.get('asistencias') in ['on', 'True', 'true', '1'],
            permite_eventos=request.POST.get('eventos') in ['on', 'True', 'true', '1'],
            # 🚀 AQUÍ GUARDAMOS EL ESTADO DE LA TIENDA EN EL PLAN
            permite_tienda=request.POST.get('tienda') in ['on', 'True', 'true', '1']
        )
        return redirect('saas_core:panel_maestro_dashboard')


class ActualizarLicenciaSaaSView(UserPassesTestMixin, View):
    """
    Controla el modal maestro de configuración de la academia.
    Genera cobro automático si pasa de SUSPENDIDO a ACTIVO.
    """
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
        
        # 1. Guardamos el estado en el que estaba ANTES de guardar
        estado_anterior = suscripcion.estado
        estado_nuevo = request.POST.get('estado')
        
        # 2. Actualizamos el Plan si lo cambiaron en el select
        nuevo_plan_id = request.POST.get('plan_id')
        if nuevo_plan_id:
            try:
                suscripcion.plan = PlanSaaS.objects.get(id=nuevo_plan_id)
            except PlanSaaS.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'El plan no existe.'}, status=400)

        # 3. Validamos si es Partner VIP ANTES de hacer cálculos
        suscripcion.es_cuenta_partner_gratis = request.POST.get('es_cuenta_partner_gratis') in ['on', 'True', 'true', '1']

        # 🚀 4. MAGIA FINANCIERA: Si estaba suspendida y la activaste
        if estado_anterior == 'SUSPENDIDO' and estado_nuevo == 'ACTIVO':
            hoy_colombia = timezone.localtime(timezone.now()).date()
            
            # Le damos sus 30 días de servicio
            suscripcion.fecha_inicio = hoy_colombia
            suscripcion.fecha_vencimiento = hoy_colombia + timezone.timedelta(days=30)

            # Si NO es gratis, facturamos en tu panel de finanzas maestro
            if not suscripcion.es_cuenta_partner_gratis:
                ReciboSaaS.objects.create(
                    academia=suscripcion.academia,
                    plan=suscripcion.plan,
                    monto=suscripcion.plan.precio_mensual,
                    concepto=f"Asignación/Activación de Licencia (30 días) - Plan: {suscripcion.plan.nombre}",
                    medio_pago="ASIGNACIÓN MANUAL (MODAL LICENCIA)"
                )

        # 5. Guardamos el nuevo estado y los superpoderes manuales
        suscripcion.estado = estado_nuevo
        suscripcion.bloqueo_manual_estudiantes = not (request.POST.get('modulo_estudiantes_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_asistencias = not (request.POST.get('modulo_asistencias_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_finanzas = not (request.POST.get('modulo_finanzas_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_multimedia = not (request.POST.get('modulo_multimedia_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_eventos = not (request.POST.get('modulo_eventos_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_tienda = not (request.POST.get('modulo_tienda_activo') in ['on', 'True', 'true', '1'])
        
        suscripcion.save()

        academia = suscripcion.academia
        academia.es_solo_eventos = request.POST.get('es_solo_eventos') in ['on', 'True', 'true', '1']
        academia.save()

        return JsonResponse({'status': 'success'})

class APIObtenerEstudiantesAcademiaView(UserPassesTestMixin, View):
    """API de Soporte: Retorna los alumnos de un inquilino para el Súper Admin."""
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def get(self, request, *args, **kwargs):
        academia_id = request.GET.get('academia_id')
        
        # 🎯 CORRECCIÓN: Cambiamos 'nombre' por 'nombres' y agregamos 'apellidos'
        estudiantes = Estudiante.unfiltered_objects.filter(academia_id=academia_id).values(
            'id', 'nombres', 'apellidos', 'identificacion', 'estado', 'fecha_registro'
        )
        
        return JsonResponse({'status': 'success', 'estudiantes': list(estudiantes)})
    

class IndexSaaSGlobalView(TemplateView):
    template_name = "saas_core/index_global.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = LandingPageConfig.objects.first()
        context['capturas'] = ScreenshotLanding.objects.filter(activo=True)
        context['beneficios'] = BeneficioLanding.objects.filter(activo=True)
        context['faqs'] = FAQLanding.objects.filter(activo=True)
        context['testimonios'] = TestimonioLanding.objects.filter(activo=True)

        context['academias_trust'] = Academia.unfiltered_objects.filter(
            activo=True
        ).order_by('-id')

        # 🚀 NUEVO: Cartelera Global de Eventos
        try:
            # Traemos los próximos 6 eventos activos
            # 🚀 LÓGICA SENIOR: Calculamos el "precio a mostrar" unificando viejo y nuevo
            context['eventos_globales'] = Evento.unfiltered_objects.filter(
                academia__activo=True,
                fecha__gte=timezone.now(),
                estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
            ).annotate(
                # Busca el precio mínimo de sus pases. Si no tiene, usa su precio_preventa original.
                precio_minimo_calculado=Coalesce(Min('pases_personalizados__precio'), 'precio_preventa')
            ).select_related('academia').order_by('fecha')[:6]
        except Exception:
            context['eventos_globales'] = []

        return context
    

class MasterActualizarLandingView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        try:
            # 1. Configuración Básica
            if action == 'general':
                config = LandingPageConfig.objects.first() or LandingPageConfig()
                config.titulo_principal = request.POST.get('titulo_principal')
                config.subtitulo_principal = request.POST.get('subtitulo_principal')
                config.boton_principal_texto = request.POST.get('boton_principal_texto')
                config.whatsapp = request.POST.get('whatsapp')
                config.email_contacto = request.POST.get('email_contacto')
                config.mostrar_capturas = 'mostrar_capturas' in request.POST
                config.mostrar_faq = 'mostrar_faq' in request.POST
                config.save()

            elif action == 'captura_add':
                ScreenshotLanding.objects.create(
                    titulo=request.POST.get('titulo'),
                    imagen=request.FILES.get('imagen')
                )

            elif action == 'captura_del':
                ScreenshotLanding.objects.get(id=request.POST.get('id')).delete()

            elif action == 'testimonio_add':
                TestimonioLanding.objects.create(
                    nombre=request.POST.get('nombre'),
                    comentario=request.POST.get('comentario'),
                    foto=request.FILES.get('foto')
                )

            # 2. Manejo de Imágenes de Capturas (Ejemplo rápido)
            if request.FILES:
                for key, file in request.FILES.items():
                    if 'nueva_captura' in key:
                        ScreenshotLanding.objects.create(
                            titulo=request.POST.get('nueva_captura_titulo', 'Imagen'),
                            imagen=file
                        )

            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        

class EliminarPlanSaaSView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser

    def post(self, request, plan_id):
        plan = get_object_or_404(PlanSaaS, id=plan_id)
        # Opcional: verificar si tiene academias asociadas antes de borrar
        if SuscripcionAcademia.objects.filter(plan=plan).exists():
            return JsonResponse({'status': 'error', 'message': 'No puedes borrar un plan en uso.'}, status=400)
        plan.delete()
        return JsonResponse({'status': 'success'})
    
class EditarPlanSaaSView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser

    def post(self, request, plan_id):
        plan = get_object_or_404(PlanSaaS, id=plan_id)
        plan.nombre = request.POST.get('nombre')
        plan.precio_mensual = request.POST.get('precio')
        plan.max_estudiantes = request.POST.get('max_estudiantes')
        
        # Guardamos permisos
        plan.permite_estudiantes = request.POST.get('estudiantes') == 'on'
        plan.permite_asistencias_qr = request.POST.get('asistencias') == 'on'
        plan.permite_finanzas = request.POST.get('finanzas') == 'on'
        plan.permite_multimedia = request.POST.get('multimedia') == 'on'
        plan.permite_eventos = request.POST.get('eventos') == 'on'
        plan.permite_tienda = request.POST.get('tienda') == 'on'
        
        plan.save()
        return JsonResponse({'status': 'success'})
    

# apps/saas_core/views.py

class MasterConfirmarPagoAcademiaView(UserPassesTestMixin, View):
    """Endpoint del Panel Maestro para confirmar un pago manual y renovar licencia. Genera ReciboSaaS."""
    
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        nuevo_plan_id = request.POST.get('plan_id')
        meses_a_renovar = int(request.POST.get('meses_a_renovar', 1))
        
        suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
        hoy_colombia = timezone.localtime(timezone.now()).date()
        
        with transaction.atomic():
            if nuevo_plan_id and int(nuevo_plan_id) != suscripcion.plan.id:
                suscripcion.plan = get_object_or_404(PlanSaaS, id=nuevo_plan_id)
            
            base_fecha = suscripcion.fecha_vencimiento if suscripcion.fecha_vencimiento >= hoy_colombia else hoy_colombia
            suscripcion.fecha_vencimiento = base_fecha + timezone.timedelta(days=meses_a_renovar * 30)
            suscripcion.estado = 'ACTIVO'
            suscripcion.save()

            # 🚀 LÓGICA DE RECIBOS: Genera ReciboSaaS SOLO si NO es cuenta partner
            if not suscripcion.es_cuenta_partner_gratis:
                monto_calculado = suscripcion.plan.precio_mensual * meses_a_renovar
                ReciboSaaS.objects.create(
                    academia=suscripcion.academia,
                    plan=suscripcion.plan,
                    monto=monto_calculado,
                    concepto=f"Renovación de Licencia ({meses_a_renovar} mes/es) - Plan: {suscripcion.plan.nombre}",
                    medio_pago="MANUAL_MASTER"
                )
            
            try:
                enviar_correo_transaccional(
                    asunto=f"¡Pago Confirmado! Tu licencia ha sido renovada - AppDanza",
                    template_name="comunicaciones/pago_confirmado_academia.html",
                    context={
                        'academia': suscripcion.academia,
                        'suscripcion': suscripcion,
                        'nueva_fecha_vencimiento': suscripcion.fecha_vencimiento
                    },
                    destinatarios=[suscripcion.academia.usuarios.filter(perfil__rol='ADMIN_ACADEMIA').first().user.email]
                )
            except Exception as e:
                print(f"Error enviando correo de confirmación: {e}")

        return JsonResponse({
            'status': 'success', 
            'message': 'Pago procesado con éxito, licencia extendida.',
            'nuevo_vencimiento': suscripcion.fecha_vencimiento.strftime('%d/%m/%Y')
        })
    
class GuardarConfigPagoGlobalView(UserPassesTestMixin, View):
    """Vista del Panel Maestro para guardar/actualizar el método único de pago del SaaS."""
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        # Implementación estilo Singleton: Traemos el único registro existente o inicializamos uno nuevo
        config_actual = ConfigPagoGlobalSaaS.objects.first()
        form = ConfigPagoSaaSForm(request.POST, instance=config_actual)
        
        if form.is_valid():
            form.save()
            messages.success(request, "¡Configuración de recaudo global actualizada correctamente!")
        else:
            messages.error(request, "Error al procesar el formulario de pagos.")
            
        return redirect('saas_core:panel_maestro_dashboard')
    

class ToggleBloqueoSaaSView(UserPassesTestMixin, View):
    """
    Activa o suspende manualmente una academia desde el switch rápido de la tabla.
    También genera recibos y suma días si se usa para activar.
    """
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            academia_id = data.get('academia_id')
            estado_deseado = data.get('estado') # 'ACTIVO' o 'SUSPENDIDO'

            suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
            estado_anterior = suscripcion.estado

            # 🚀 MAGIA FINANCIERA TAMBIÉN EN EL SWITCH
            if estado_anterior == 'SUSPENDIDO' and estado_deseado == 'ACTIVO':
                hoy_colombia = timezone.localtime(timezone.now()).date()
                
                suscripcion.fecha_inicio = hoy_colombia
                suscripcion.fecha_vencimiento = hoy_colombia + timezone.timedelta(days=30)

                if not suscripcion.es_cuenta_partner_gratis:
                    ReciboSaaS.objects.create(
                        academia=suscripcion.academia,
                        plan=suscripcion.plan,
                        monto=suscripcion.plan.precio_mensual,
                        concepto=f"Reactivación Rápida de Licencia (30 días) - Plan: {suscripcion.plan.nombre}",
                        medio_pago="SWITCH MANUAL (TABLA MAESTRA)"
                    )

            suscripcion.estado = estado_deseado
            suscripcion.save()

            return JsonResponse({'status': 'success', 'nuevo_estado': suscripcion.estado})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        

class SubirComprobanteSaaSView(View):
    """Vista que recibe el comprobante desde la academia (Bloqueada o Activa)."""
    
    def post(self, request, *args, **kwargs):
        # 1. 🚀 SOLUCIÓN: Capturamos el ID directamente desde el formulario oculto
        academia_id = request.POST.get('academia_id')
        academia = get_object_or_404(Academia, id=academia_id)
        
        archivo = request.FILES.get('comprobante')
        
        if archivo:
            # 2. Guardamos el reporte vinculándolo a la academia que encontramos
            reporte = ReportePagoSaaS.objects.create(
                academia=academia,
                plan=academia.suscripcion_saas.plan,
                comprobante=archivo
            )
            
            # 3. Enviamos el correo de alerta al Admin Maestro
            url_revision = request.build_absolute_uri(reverse('saas_core:master_revisar_pago', args=[reporte.id]))
            
            try:
                send_mail(
                    subject=f"🚨 Nuevo Pago de Licencia: {academia.nombre}",
                    message=f"La academia {academia.nombre} ha subido un comprobante de pago.\n\n"
                            f"Plan: {reporte.plan.nombre}\n"
                            f"Fecha: {reporte.fecha_envio.strftime('%d/%m/%Y %H:%M')}\n\n"
                            f"👉 Haz clic aquí para ver el comprobante y aprobar la renovación:\n{url_revision}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=['appdanza2026@gmail.com'], 
                    fail_silently=True
                )
            except Exception as e:
                pass 

            messages.success(request, "¡Comprobante enviado con éxito! En unos minutos verificaremos tu pago y reactivaremos tu plataforma.")
        else:
            messages.error(request, "Por favor, selecciona un archivo válido.")
            
        return redirect(request.META.get('HTTP_REFERER', '/'))


class RevisarYAprobarPagoView(UserPassesTestMixin, View):
    """Vista para el Maestro: Muestra el comprobante, renueva la academia y genera ReciboSaaS."""
    
    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, pk):
        reporte = get_object_or_404(ReportePagoSaaS, pk=pk)
        return render(request, 'saas_core/revision_pago.html', {'reporte': reporte})

    def post(self, request, pk):
        reporte = get_object_or_404(ReportePagoSaaS, pk=pk)
        suscripcion = reporte.academia.suscripcion_saas
        hoy = timezone.now().date()
        
        with transaction.atomic():
            reporte.estado = 'APROBADO'
            reporte.save()
            
            base_fecha = suscripcion.fecha_vencimiento if suscripcion.fecha_vencimiento > hoy else hoy
                
            suscripcion.estado = 'ACTIVO'
            suscripcion.fecha_inicio = hoy
            suscripcion.fecha_vencimiento = base_fecha + timezone.timedelta(days=30)
            suscripcion.save()

            # 🚀 LÓGICA DE RECIBOS: Genera ReciboSaaS SOLO si NO es cuenta partner
            if not suscripcion.es_cuenta_partner_gratis:
                ReciboSaaS.objects.create(
                    academia=reporte.academia,
                    plan=reporte.plan,
                    monto=reporte.plan.precio_mensual,
                    concepto=f"Pago Licencia Mensual - Comprobante de validación #{reporte.id}",
                    medio_pago="TRANSFERENCIA/COMPROBANTE"
                )
        
        messages.success(request, f"¡Suscripción de {reporte.academia.nombre} renovada hasta el {suscripcion.fecha_vencimiento.strftime('%d/%m/%Y')}!")
        return redirect('saas_core:panel_maestro_dashboard')
    

class FinanzasMaestroDashboardView(UserPassesTestMixin, TemplateView):
    template_name = 'saas_core/finanzas_dashboard.html'

    def test_func(self):
        # Aseguramos que solo el SuperAdmin (Tú) tenga acceso
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Filtramos por el mes y año actual para los indicadores rápidos
        hoy = timezone.now()
        mes_actual = hoy.month
        anio_actual = hoy.year

        # --- INGRESOS ---
        recibos_mes = ReciboSaaS.objects.filter(fecha__month=mes_actual, fecha__year=anio_actual)
        ingresos_mes = recibos_mes.aggregate(total=Sum('monto'))['total'] or 0

        # --- GASTOS ---
        gastos_mes = GastoSaaS.objects.filter(fecha__month=mes_actual, fecha__year=anio_actual)
        gastos_total_mes = gastos_mes.aggregate(total=Sum('monto'))['total'] or 0

        # --- BALANCE ---
        balance_neto = ingresos_mes - gastos_total_mes

        # Inyectamos al contexto (Listados limitados a 50 para no saturar memoria en PythonAnywhere)
        context['ingresos_mes'] = ingresos_mes
        context['gastos_mes'] = gastos_total_mes
        context['balance_neto'] = balance_neto
        context['ultimos_recibos'] = ReciboSaaS.objects.all()[:50]
        context['ultimos_gastos'] = GastoSaaS.objects.all()[:50]
        
        # 🚀 LA PIEZA FALTANTE: Instanciamos el form y lo pasamos al template
        context['form_gasto'] = GastoSaaSForm() 
        
        return context
    

class DescargarReciboSaaSPDFView(UserPassesTestMixin, View):
    """Genera la Cuenta de Cobro en PDF usando ReportLab (Súper ligero para PythonAnywhere)"""
    
    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, recibo_id):
        recibo = get_object_or_404(ReciboSaaS, id=recibo_id)
        
        # Creamos un buffer en memoria RAM temporal (Súper rápido)
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # --- CABECERA (Inspirada en tu Cuenta_Cobro_RC-0001.pdf) ---
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, "AppDanza SaaS CORE")
        
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 70, "Razón Social: Duane Abreu")
        p.drawString(50, height - 85, "NIT/C.C.: 1414772")
        
        # --- NÚMERO DE RECIBO A LA DERECHA ---
        p.setFont("Helvetica-Bold", 14)
        p.drawString(width - 250, height - 50, "CUENTA DE COBRO")
        p.setFont("Helvetica", 12)
        p.drawString(width - 200, height - 70, f"N° {recibo.numero_recibo}")

        # --- DATOS DEL CLIENTE ---
        p.line(50, height - 100, width - 50, height - 100) # Línea separadora
        
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, height - 120, "Adquiriente / Cliente:")
        p.setFont("Helvetica", 10)
        p.drawString(200, height - 120, f"{recibo.academia.nombre} (NIT/CC: No Registrado)")

        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, height - 140, "Fecha de Emisión:")
        p.setFont("Helvetica", 10)
        p.drawString(200, height - 140, f"{recibo.fecha.strftime('%d/%m/%Y')}")

        # --- TABLA DE CONCEPTOS ---
        p.line(50, height - 160, width - 50, height - 160)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, height - 175, "Concepto / Descripción del Ingreso")
        p.drawString(450, height - 175, "Valor COP")
        p.line(50, height - 185, width - 50, height - 185)

        p.setFont("Helvetica", 10)
        p.drawString(50, height - 205, f"{recibo.concepto}")
        p.drawString(450, height - 205, f"$ {recibo.monto:,.2f}")

        # --- TOTAL ---
        p.line(50, height - 225, width - 50, height - 225)
        p.setFont("Helvetica-Bold", 12)
        p.drawString(300, height - 245, "TOTAL A PAGAR:")
        p.drawString(450, height - 245, f"$ {recibo.monto:,.2f}")

        # --- PIE DE PÁGINA (Legal) ---
        p.setFont("Helvetica-Oblique", 8)
        p.drawString(50, height - 350, "Documento equivalente a cuenta de cobro para no obligados a facturar (Art. 1.6.1.4.12 Decreto 1625 de 2016).")
        p.drawString(50, height - 365, "Documento de control interno no válido como factura con impuestos descontables.")
        p.drawString(50, height - 380, "Generado por SaaS AppDanza Hub CORE v1.0.")

        # Cierra el PDF
        p.showPage()
        p.save()
        buffer.seek(0)
        
        return FileResponse(buffer, as_attachment=True, filename=f"Cuenta_Cobro_{recibo.numero_recibo}.pdf")
    

# 1. VISTA PARA GUARDAR EL GASTO SAAS
class RegistrarGastoSaaSView(UserPassesTestMixin, SuccessMessageMixin, CreateView):
    """Guarda un gasto operativo del dueño de la plataforma."""
    model = GastoSaaS
    form_class = GastoSaaSForm
    template_name = 'saas_core/finanzas_dashboard.html' # Aunque usa modal, requiere esto por si hay error
    success_url = reverse_lazy('saas_core:master_finanzas')
    success_message = "¡Gasto operativo registrado exitosamente!"

    def test_func(self):
        return self.request.user.is_superuser

    def form_invalid(self, form):
        messages.error(self.request, "Error al registrar el gasto. Verifica los datos.")
        return redirect('saas_core:master_finanzas')
    

# 2. VISTA AJAX PARA EL MODAL DEL RECIBO/GASTO
class ObtenerDetalleTransaccionSaaSView(UserPassesTestMixin, View):
    """Retorna los datos de un Ingreso (ReciboSaaS) o Egreso (GastoSaaS) en JSON."""
    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, tipo, pk):
        if tipo == 'ingreso':
            item = get_object_or_404(ReciboSaaS, pk=pk)
            data = {
                'consecutivo': item.numero_recibo,
                'fecha': item.fecha.strftime('%d/%m/%Y'),
                'tipo_badge': 'Ingreso Licencia',
                'tercero_nombre': item.academia.nombre,
                'concepto': item.concepto,
                'medio_pago': item.medio_pago,
                'monto': float(item.monto),
                'estado': 'ACTIVO',
                'es_gasto': False
            }
        elif tipo == 'gasto':
            item = get_object_or_404(GastoSaaS, pk=pk)
            data = {
                'consecutivo': f"GS-{item.id:04d}", # Gasto SaaS auto-formateado
                'fecha': item.fecha.strftime('%d/%m/%Y'),
                'tipo_badge': 'Gasto Operativo',
                'tercero_nombre': 'SaaS Hub Core',
                'concepto': item.concepto,
                'medio_pago': 'N/A',
                'monto': float(item.monto),
                'estado': 'ACTIVO',
                'es_gasto': True,
                'url_comprobante': item.comprobante.url if item.comprobante else None
            }
        else:
            return JsonResponse({'error': 'Tipo no válido'}, status=400)
            
        return JsonResponse(data)


# 3. VISTA PARA EXPORTAR EL CSV CONTABLE GLOBAL
class ExportarContabilidadSaaSView(UserPassesTestMixin, View):
    """Exporta Ingresos y Gastos del Master en CSV."""
    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request):
        mes = request.GET.get('mes', timezone.now().month)
        anio = request.GET.get('anio', timezone.now().year)

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="Contabilidad_SaaS_{mes}_{anio}.csv"'
        
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['Fecha', 'Referencia', 'Tipo', 'Tercero/Academia', 'Concepto', 'Ingreso', 'Egreso'])

        # Ingresos
        ingresos = ReciboSaaS.objects.filter(fecha__month=mes, fecha__year=anio)
        for ing in ingresos:
            writer.writerow([
                ing.fecha.strftime('%d/%m/%Y'), ing.numero_recibo, 'INGRESO', 
                ing.academia.nombre, ing.concepto, ing.monto, 0
            ])
            
        # Gastos
        gastos = GastoSaaS.objects.filter(fecha__month=mes, fecha__year=anio)
        for gas in gastos:
            writer.writerow([
                gas.fecha.strftime('%d/%m/%Y'), f"GS-{gas.id:04d}", 'EGRESO', 
                'Operativo SaaS', gas.concepto, 0, gas.monto
            ])
            
        return response