from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from apps.academias.models import Academia, PerfilUsuario
from django.core.mail import send_mail
from django.conf import settings
from .forms import ConfigPagoSaaSForm
from .models import PlanSaaS, SuscripcionAcademia

from django.shortcuts import get_object_or_404, render
from django.views import View
from django.http import JsonResponse
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
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        nombre = request.POST.get('nombre')
        slug = request.POST.get('slug')
        plan_id = request.POST.get('plan_id')
        dias_prueba = int(request.POST.get('dias_prueba', 15))
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

            # 2. Obtenemos el plan comercial maestro seleccionado
            plan_inicial = PlanSaaS.objects.get(id=plan_id)
            fecha_hoy = timezone.now().date()
            
            # 🎯 REPARACIÓN SENIOR: Eliminamos la declaración de los módulos.
            # Como los módulos son `@property` que heredan los permisos del 'plan', 
            # no es necesario ni permitido guardarlos explícitamente aquí.
            # Los campos reales 'bloqueo_manual_*' nacen en False por defecto en tu modelo.
            SuscripcionAcademia.objects.create(
                academia=nueva_academia,
                plan=plan_inicial,
                estado='PRUEBA',
                ya_uso_prueba_gratis=True,
                dias_regalados_prueba=dias_prueba,
                fecha_inicio=fecha_hoy,
                fecha_vencimiento=fecha_hoy + timezone.timedelta(days=dias_prueba)
            )

            # 3. Credenciales de acceso de su respectivo director técnico
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

            # 🚀 DISPARADOR DE CORREO: Bienvenida SaaS
            enviar_correo_transaccional(
                asunto=f"¡Bienvenido a AppDanza, {nueva_academia.nombre}!",
                template_name="comunicaciones/bienvenida_academia.html",
                context={
                    'academia': nueva_academia  # Instancia real de la BD
                },
                destinatarios=[admin_email]
            )

        return redirect('panel_maestro_dashboard')


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
        return redirect('panel_maestro_dashboard')


class ActualizarLicenciaSaaSView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
        
        suscripcion.estado = request.POST.get('estado')
        
        nuevo_plan_id = request.POST.get('plan_id')
        if nuevo_plan_id:
            try:
                suscripcion.plan = PlanSaaS.objects.get(id=nuevo_plan_id)
            except PlanSaaS.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'El plan no existe.'}, status=400)

        # 🚀 LÓGICA INVERSA: Si el frontend dice "Módulo Activo = True", el Bloqueo es "False"
        suscripcion.bloqueo_manual_estudiantes = not (request.POST.get('modulo_estudiantes_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_asistencias = not (request.POST.get('modulo_asistencias_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_finanzas = not (request.POST.get('modulo_finanzas_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_multimedia = not (request.POST.get('modulo_multimedia_activo') in ['on', 'True', 'true', '1'])
        suscripcion.bloqueo_manual_eventos = not (request.POST.get('modulo_eventos_activo') in ['on', 'True', 'true', '1'])
        
        # 🚀 LA CLAVE ESTÁ AQUÍ: Interceptar la tienda
        suscripcion.bloqueo_manual_tienda = not (request.POST.get('modulo_tienda_activo') in ['on', 'True', 'true', '1'])
        
        suscripcion.es_cuenta_partner_gratis = request.POST.get('es_cuenta_partner_gratis') in ['on', 'True', 'true', '1']
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
            # Traemos los próximos 6 eventos que estén activos, de academias activas.
            context['eventos_globales'] = Evento.unfiltered_objects.filter(
                academia__activo=True,  # Seguridad: que la academia no esté bloqueada
                fecha__gte=timezone.now(),
                estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
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
    """Endpoint del Panel Maestro para confirmar un pago manual y renovar licencia."""
    
    def test_func(self):
        # Seguridad absoluta: Solo tú o tu staff administrativo global
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        nuevo_plan_id = request.POST.get('plan_id')
        meses_a_renovar = int(request.POST.get('meses_a_renovar', 1)) # Por defecto 1 mes
        
        suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
        hoy_colombia = timezone.localtime(timezone.now()).date()
        
        with transaction.atomic():
            # 1. Gestión y cambio de Plan si el SuperAdmin lo decidió
            if nuevo_plan_id and int(nuevo_plan_id) != suscripcion.plan.id:
                nuevo_plan = get_object_or_404(PlanSaaS, id=nuevo_plan_id)
                suscripcion.plan = nuevo_plan
            
            # 2. Cálculo inteligente de la nueva fecha de vencimiento:
            # Si la academia ya estaba bloqueada/vencida, su nuevo periodo inicia HOY.
            # Si pagó antes del vencimiento, se le acumulan los días sumando desde su fecha de vencimiento actual.
            base_fecha = suscripcion.fecha_vencimiento if suscripcion.fecha_vencimiento >= hoy_colombia else hoy_colombia
            
            # Estimación estándar de meses comerciales (30 días por mes para evitar saltos extraños)
            dias_a_sumar = meses_a_renovar * 30
            suscripcion.fecha_vencimiento = base_fecha + timezone.timedelta(days=dias_a_sumar)
            
            # 3. Restauración de estados de cuenta
            suscripcion.estado = 'ACTIVO'
            suscripcion.save()
            
            # 🚀 DISPARADOR DE CORREO: Notificación de pago exitoso al director de la academia
            try:
                enviar_correo_transaccional(
                    asunto=f"¡Pago Confirmado! Tu licencia ha sido renovada - AppDanza",
                    template_name="comunicaciones/pago_confirmado_academia.html",
                    context={
                        'academia': suscripcion.academia,
                        'suscripcion': suscripcion,
                        'nueva_fecha_vencimiento': suscripcion.fecha_vencimiento
                    },
                    destatarios=[suscripcion.academia.usuarios.filter(perfil__rol='ADMIN_ACADEMIA').first().user.email]
                )
            except Exception as e:
                # Loggear el error de correo pero no tumbar la transacción de la BD
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
            
        return redirect('panel_maestro_dashboard')
    

class ToggleBloqueoSaaSView(UserPassesTestMixin, View):
    """Activa o suspende manualmente una academia desde el switch del Dashboard Maestro."""
    
    def test_func(self):
        # Seguridad: Solo el dueño del SaaS puede jalar este gatillo
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        try:
            # Capturamos la data enviada por JS vía fetch
            data = json.loads(request.body)
            academia_id = data.get('academia_id')
            estado_deseado = data.get('estado') # Será 'ACTIVO' o 'SUSPENDIDO'

            # Traemos la suscripción y le cambiamos el estado
            suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
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
    """Vista para el Maestro: Muestra el comprobante y renueva la academia con 1 click."""
    
    def test_func(self):
        return self.request.user.is_superuser

    def get(self, request, pk):
        # Renderiza una plantilla simple para ver el comprobante
        reporte = get_object_or_404(ReportePagoSaaS, pk=pk)
        return render(request, 'saas_core/revision_pago.html', {'reporte': reporte})

    def post(self, request, pk):
        # 🚀 ACCIÓN DE APROBAR Y RENOVAR
        reporte = get_object_or_404(ReportePagoSaaS, pk=pk)
        suscripcion = reporte.academia.suscripcion_saas
        
        # 1. Marcamos el pago como aprobado
        reporte.estado = 'APROBADO'
        reporte.save()
        
        # 2. Lógica inteligente de renovación
        hoy = timezone.now().date()
        
        # Si la suscripción aún no ha vencido, partimos desde el vencimiento actual.
        # Si ya venció (fecha < hoy), partimos desde hoy.
        if suscripcion.fecha_vencimiento > hoy:
            base_fecha = suscripcion.fecha_vencimiento
        else:
            base_fecha = hoy
            
        suscripcion.estado = 'ACTIVO'
        suscripcion.fecha_inicio = hoy
        # Sumamos 30 días a la fecha base calculada
        suscripcion.fecha_vencimiento = base_fecha + timezone.timedelta(days=30)
        suscripcion.save()
        
        messages.success(request, f"¡Suscripción de {reporte.academia.nombre} renovada hasta el {suscripcion.fecha_vencimiento.strftime('%d/%m/%Y')}!")
        return redirect('saas_core:panel_maestro_dashboard')