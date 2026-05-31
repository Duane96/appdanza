from django.views.generic import TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from apps.academias.models import Academia, PerfilUsuario
from .models import PlanSaaS, SuscripcionAcademia

from django.shortcuts import get_object_or_404
from django.views import View
from django.http import JsonResponse

from django.shortcuts import redirect
from django.urls import reverse
from apps.planes_estudiantes.models import Estudiante
from .models import PlanSaaS, SuscripcionAcademia
from django.utils import timezone

from django.db import transaction

from django.contrib.auth.models import User

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
        
        # 🎨 CAPTURA EL CAMPO PREMIUM DE MARCA BLANCA
        template_personalizado = request.POST.get('template_landing_personalizado', '').strip()
        if not template_personalizado:
            template_personalizado = None

        # 🎫 CAPTURA MODO PRODUCTORA DE EVENTOS
        es_productora = request.POST.get('es_solo_eventos') == 'on'

        admin_email = request.POST.get('admin_email')
        admin_password = request.POST.get('admin_password')

        with transaction.atomic():
            nueva_academia = Academia.unfiltered_objects.create(
                nombre=nombre,
                slug=slug,
                template_landing_personalizado=template_personalizado,
                es_solo_eventos=es_productora, # 👈 AQUÍ SE GUARDA EL MODO
                activo=True
            )

            plan_inicial = PlanSaaS.objects.get(id=plan_id)
            fecha_hoy = timezone.now().date()
            SuscripcionAcademia.objects.create(
                academia=nueva_academia,
                plan=plan_inicial,
                estado='PRUEBA',
                ya_uso_prueba_gratis=True,
                dias_regalados_prueba=dias_prueba,
                fecha_inicio=fecha_hoy,
                fecha_vencimiento=fecha_hoy + timezone.timedelta(days=dias_prueba) 
            )

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

class ActualizarLicenciaSaaSView(UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        academia_id = request.POST.get('academia_id')
        
        # OBTENEMOS LOS OBJETOS
        suscripcion = get_object_or_404(SuscripcionAcademia, academia_id=academia_id)
        academia = suscripcion.academia # 👈 Instancia directa de la academia
        
        # 1. ACTUALIZAR ESTADO DE SUSCRIPCIÓN
        suscripcion.estado = request.POST.get('estado')
        
        # 2. CAPTURAR CHECKBOXES
        suscripcion.bloqueo_manual_multimedia = request.POST.get('bloqueo_multimedia') == 'on'
        suscripcion.bloqueo_manual_finanzas = request.POST.get('bloqueo_finanzas') == 'on'
        suscripcion.bloqueo_manual_asistencias = request.POST.get('bloqueo_asistencias') == 'on'
        suscripcion.bloqueo_manual_eventos = request.POST.get('bloqueo_eventos') == 'on'
        suscripcion.bloqueo_manual_estudiantes = request.POST.get('bloqueo_estudiantes') == 'on'
        suscripcion.es_cuenta_partner_gratis = request.POST.get('es_cuenta_partner_gratis') == 'on'
        suscripcion.save()

        # 3. ACTUALIZAR MODO EVENTOS EN EL MODELO ACADEMIA 👈
        academia.es_solo_eventos = request.POST.get('es_solo_eventos') == 'on'
        academia.save()

        return JsonResponse({'status': 'success'})

class CrearPlanSaaSView(UserPassesTestMixin, View):
    """Crea un nuevo nivel de plan comercial para el SaaS."""
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        nombre = request.POST.get('nombre')
        precio = request.POST.get('precio')
        max_estudiantes = request.POST.get('max_estudiantes')
        
        PlanSaaS.objects.create(
            nombre=nombre,
            precio_mensual=precio,
            max_estudiantes=max_estudiantes,
            permite_estudiantes=request.POST.get('estudiantes') == 'on', # 🚀 NUEVO
            permite_multimedia=request.POST.get('multimedia') == 'on',
            permite_finanzas=request.POST.get('finanzas') == 'on',
            permite_asistencias_qr=request.POST.get('asistencias') == 'on'
        )
        return redirect('panel_maestro_dashboard')


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
    """Landing Page principal de la plataforma SaaS (Vitrina comercial externa)."""
    template_name = "saas_core/index_global.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Traemos todos los planes configurados en el sistema para la tabla comparativa de precios
        context['planes'] = PlanSaaS.objects.all().order_by('precio_mensual')
        return context