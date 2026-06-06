from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from apps.academias.models import Academia, PerfilUsuario
from .models import PlanSaaS, SuscripcionAcademia

from django.shortcuts import get_object_or_404
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

class PanelMaestroDashboardView(UserPassesTestMixin, TemplateView):
    """Centro de mando global para el dueño del SaaS (Súper Admin)."""
    template_name = "saas_core/master_dashboard.html"

    def test_func(self):
        """Filtro de seguridad estricto: Solo superusuarios reales del sistema."""
        return self.request.user.is_superuser and self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 🎯 REPARACIÓN SENIOR: Usamos 'unfiltered_objects' para consultas globales sin restricción
        context['total_academias'] = Academia.unfiltered_objects.count()
        
        # Filtramos las suscripciones totales del sistema
        context['academias_activas'] = SuscripcionAcademia.objects.filter(estado='ACTIVO').count()
        context['academias_suspendidas'] = SuscripcionAcademia.objects.filter(estado='SUSPENDIDO').count()
        
        # Traemos todas las academias con sus planes mapeados de un solo golpe de base de datos
        context['academias'] = Academia.unfiltered_objects.all().select_related('suscripcion_saas__plan')
        context['planes_saas'] = PlanSaaS.objects.all()
        context['config'] = LandingPageConfig.objects.first() or LandingPageConfig()
        
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