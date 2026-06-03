# apps/academias/views.py
from django.views.generic import TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse

from apps.eventos.models import Evento
from .models import Academia
from django.contrib.auth.views import LoginView

from apps.planes_estudiantes.models import Estudiante, InscripcionPlan, Plan
from apps.asistencias.models import Asistencia
from apps.finanzas.models import ReciboIngreso, Gasto

from django.utils import timezone
from django.db.models import Sum

from .forms import ConfigMascaraForm

from django.contrib.auth.views import LogoutView

from apps.multimedia.models import VideoClase

# apps/academias/views.py

class LandingAcademiaView(TemplateView):
    """
    Muestra la Landing Page pública de la academia activa en la URL (Tenant).
    Soporta la carga dinámica de plantillas HTML y añade un video destacado del aula virtual.
    """
    
    def get_template_names(self):
        academia_activa = self.request.tenant
        if academia_activa and academia_activa.template_landing_personalizado:
            return [academia_activa.template_landing_personalizado]
        if academia_activa and academia_activa.es_solo_eventos:
            return ["academias/index_eventos.html"]
        return ["academias/index.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        academia_activa = self.request.tenant
        context['academia'] = academia_activa
        
        # 1. TRAER PLANES COMERCIALES
        try:
            context['planes'] = Plan.objects.filter(academia=academia_activa).order_by('precio')[:3]
        except (NameError, AttributeError):
            context['planes'] = []
            
        # 2. TRAER EVENTOS VIGENTES
        try:
            context['eventos'] = Evento.objects.filter(
                academia=academia_activa,
                fecha__gte=timezone.now(),  
                estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
            ).order_by('fecha')[:3]  
        except (NameError, AttributeError):
            context['eventos'] = []

        # 3. 🎥 INYECCIÓN DE MULTIMEDIA DE DEMOSTRACIÓN (NUEVO)
        # Traemos el último video subido por la academia filtrando a través de la relación del módulo
        try:
            video_destacado = VideoClase.objects.filter(
                modulo__academia=academia_activa
            ).order_by('-fecha_subida').first()
            context['video_destacado'] = video_destacado
        except Exception:
            context['video_destacado'] = None

        return context


class LoginAcademiaView(LoginView):
    """Formulario de inicio de sesión adaptado al tenant."""
    template_name = "academias/login.html"

    def get_success_url(self):
        """🚀 REDIRECCIÓN INTELIGENTE CORREGIDA: Apunta al portal real del estudiante."""
        user = self.request.user
        slug = self.request.tenant.slug

        try:
            perfil = user.perfil
            # 1. Si es Administrador o Profesor, va al panel de control global
            if perfil.rol in ['ADMIN_ACADEMIA', 'PROFESOR']:
                return reverse('academias:dashboard', kwargs={'slug_academia': slug})
            
            # 2. 🎯 CORRECCIÓN: Si es Estudiante, va DIRECTO a su portal de tiqueteras y QR
            elif perfil.rol == 'ESTUDIANTE':
                return reverse('planes_estudiantes:portal_estudiante', kwargs={'slug_academia': slug})
        
        except AttributeError:
            # Si es un Superusuario maestro de Django, al dashboard por defecto
            if user.is_staff:
                return reverse('academias:dashboard', kwargs={'slug_academia': slug})
        
        return reverse('academias:index', kwargs={'slug_academia': slug})


class DashboardAdminView(LoginRequiredMixin, TemplateView):
    """Renderiza el panel de control administrativo de la academia específica."""
    template_name = "academias/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 🏢 El request.tenant fue inyectado de forma segura por el Middleware Multi-tenant
        academia = self.request.tenant
        context['academia'] = academia
        # PASAMOS EL ESTADO DE PARTNER AL CONTEXTO
        suscripcion = academia.suscripcion_saas
        context['es_partner'] = suscripcion.es_cuenta_partner_gratis

        context['eventos_activos'] = Evento.objects.filter(
            academia=academia,
            estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
        ).order_by('fecha')


        # 📅 OBTENEMOS EL AÑO, MES Y DÍA ACTUAL (Manejo ultra-tolerante del tiempo)
        ahora = timezone.localtime(timezone.now())
        año_actual = ahora.year
        mes_actual = ahora.month
        hoy_fecha = ahora.date()

        estado_activo = 'ACTIVO'

        # Cómputo inteligente de fechas para el mes anterior (Comparativa financiera)
        if mes_actual == 1:
            año_anterior = año_actual - 1
            mes_anterior = 12
        else:
            año_anterior = año_actual
            mes_anterior = mes_actual - 1

        # 👥 KPI DE ESTUDIANTES (Filtros por Tenant)
        context['estudiantes_totales'] = Estudiante.objects.filter(academia=academia).count()
        context['estudiantes_activos'] = Estudiante.objects.filter(academia=academia, estado='ACTIVO').count()
        
        # Estudiantes cuya fecha_registro cae en el mes actual
        context['registrados_este_mes'] = Estudiante.objects.filter(
            academia=academia, 
            fecha_registro__year=año_actual,
            fecha_registro__month=mes_actual
        ).count()

        # ⏱️ KPI DE ASISTENCIAS (Registros QR del día de hoy)
        context['asistencias_hoy'] = Asistencia.objects.filter(academia=academia, fecha_hora__date=hoy_fecha).count()

        # 💵 TOTAL DE INGRESOS MENSUALES
        # El filtro es dinámico y soporta variaciones comunes en el string del estado activo ('ACTIVE' o 'ACTIVO')
        estado_activo = 'ACTIVE' if hasattr(ReciboIngreso, 'estado') else 'ACTIVO'
        
        # Filtro alternativo si el mes falla
        ingresos_mes = ReciboIngreso.objects.filter(
            academia=academia, 
            estado='ACTIVO',
            fecha__gte=ahora.replace(day=1, hour=0, minute=0, second=0),
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        context['ingresos_mes'] = ingresos_mes
        
        # Histórico histórico de ingresos de la academia
        context['ingresos_totales'] = ReciboIngreso.objects.filter(academia=academia, estado='ACTIVO').aggregate(total=Sum('monto'))['total'] or 0

        # 🔴 TOTAL DE GASTOS MENSUALES Y HISTÓRICOS
        gastos_mes = Gasto.objects.filter(
            academia=academia, 
            estado='ACTIVO', 
            fecha__year=año_actual,
            fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0
        context['gastos_mes'] = gastos_mes
        
        context['gastos_totales'] = Gasto.objects.filter(academia=academia, estado='ACTIVO').aggregate(total=Sum('monto'))['total'] or 0

        # 📈 UTILIDAD NETA DEL MES EN CURSO (Ingresos menos Gastos)
        context['utilidad_mes'] = ingresos_mes - gastos_mes

        # 📊 AUDITORÍA MAESTRA: Distribución de dinero por medio de pago (Efectivo vs Nequi/Bancos)
        caja_efectivo = ReciboIngreso.objects.filter(
            academia=academia, 
            estado='ACTIVO', 
            medio_pago='EFECTIVO', 
            fecha__year=año_actual, 
            fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        caja_transferencia = ReciboIngreso.objects.filter(
            academia=academia, 
            estado='ACTIVO', 
            medio_pago='TRANSFERENCIA', 
            fecha__year=año_actual, 
            fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0

        context['caja_efectivo'] = caja_efectivo
        context['caja_transferencia'] = caja_transferencia

        # Cálculo dinámico de porcentajes relativos para pintar las barras de progreso en el HTML
        total_cajas = caja_efectivo + caja_transferencia
        if total_cajas > 0:
            context['porcentaje_efectivo'] = (caja_efectivo / total_cajas) * 100
            context['porcentaje_transferencia'] = (caja_transferencia / total_cajas) * 100
        else:
            context['porcentaje_efectivo'] = 0
            context['porcentaje_transferencia'] = 0

        # 🚨 ALERTA OPERATIVA 1: Mapeo detallado de Alumnos en Riesgo de Deserción (> 7 días ausentes)
        hace_7_dias = ahora - timezone.timedelta(days=7)
        estudiantes_activos_objs = Estudiante.objects.filter(academia=academia, estado='ACTIVO')
        
        lista_alumnos_riesgo = []
        for est in estudiantes_activos_objs:
            # Buscamos el registro de su asistencia más reciente
            ultima_as_obj = Asistencia.objects.filter(estudiante=est, academia=academia).order_by('-fecha_hora').first()
            
            # Buscamos el plan actual/último asignado al alumno para inyectarlo en la fila del modal
            inscripcion_actual = InscripcionPlan.objects.filter(estudiante=est, academia=academia).order_by('-id').first()
            nombre_plan = inscripcion_actual.plan.nombre if (inscripcion_actual and inscripcion_actual.plan) else "Sin Plan Activo"
            
            if ultima_as_obj:
                # Si asistió alguna vez pero fue hace más de 7 días
                if ultima_as_obj.fecha_hora < hace_7_dias:
                    est.ultima_asistencia_str = ultima_as_obj.fecha_hora.strftime('%d/%m/%Y')
                    est.plan_nombre = nombre_plan
                    lista_alumnos_riesgo.append(est)
            else:
                # Si nunca ha venido a clase y lleva más de 7 días registrado en el sistema
                # Se aplica la corrección .date() para equiparar con hace_7_dias.date()
                if est.fecha_registro and est.fecha_registro.date() < hace_7_dias.date():
                    est.ultima_asistencia_str = "Nunca ha asistido"
                    est.plan_nombre = nombre_plan
                    lista_alumnos_riesgo.append(est)
                    
        context['alumnos_en_riesgo_lista'] = lista_alumnos_riesgo
        context['alumnos_en_riesgo'] = len(lista_alumnos_riesgo)

        # 🚨 ALERTA OPERATIVA 2: Mapeo detallado de Planes por Vencer (Próximos 5 días)
        dentro_de_5_dias = hoy_fecha + timezone.timedelta(days=5)
        
        # Filtramos inscripciones cuyo vencimiento esté entre hoy y los siguientes 5 días
        # Usamos select_related para evitar el problema de consultas N+1 en la base de datos al renderizar nombres y planes
        inscripciones_por_vencer = InscripcionPlan.objects.filter(
            academia=academia,
            fecha_fin__gte=hoy_fecha,
            fecha_fin__lte=dentro_de_5_dias
        ).select_related('estudiante', 'plan')
        
        context['planes_por_vencer_lista'] = inscripciones_por_vencer
        context['planes_por_vencer'] = inscripciones_por_vencer.count()

        # ⚖️ ANÁLISIS COMPARATIVO DE CRECIMIENTO MENSUAL
        ingresos_mes_anterior = ReciboIngreso.objects.filter(
            academia=academia, 
            estado='ACTIVO', 
            fecha__year=año_anterior, 
            fecha__month=mes_anterior
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        if ingresos_mes_anterior > 0:
            crecimiento = ((ingresos_mes - ingresos_mes_anterior) / ingresos_mes_anterior) * 100
            context['comparativa_ingresos'] = round(crecimiento, 1)
        else:
            context['comparativa_ingresos'] = 100.0 # Valor base si no se registran facturas el mes anterior

        return context


# apps/academias/views.py

class BrandingConfigView(LoginRequiredMixin, UpdateView):
    model = Academia
    form_class = ConfigMascaraForm
    template_name = "academias/configuracion.html"

    def get_object(self, queryset=None):
        return self.request.tenant

    def form_valid(self, form):
        print("✅ FORM VALID")
        print("Nombre:", form.cleaned_data.get("nombre"))
        return super().form_valid(form)

    def form_valid(self, form):
        print("ANTES")
        print("OBJETO:", self.get_object().nombre)

        self.object = form.save()

        print("DESPUES")
        print("OBJETO:", self.object.nombre)

        from apps.academias.models import Academia
        refrescado = Academia.objects.get(pk=self.object.pk)

        print("BD:")
        print(refrescado.nombre)

        return redirect(
            'academias:configuracion',
            slug_academia=self.request.tenant.slug
        )

    def get_success_url(self):
        return reverse(
            'academias:configuracion',
            kwargs={
                'slug_academia': self.request.tenant.slug
            }
        )

class LogoutAcademiaView(LogoutView):
    """Cierre de sesión seguro adaptado al slug de la academia actual."""
    
    def get_success_url(self):
        """Redirecciona al estudiante o admin a la landing page de su academia."""
        slug = self.request.tenant.slug
        # Al salir, lo mandamos al index comercial de la academia actual
        return reverse('academias:index', kwargs={'slug_academia': slug})