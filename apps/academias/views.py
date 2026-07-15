# apps/academias/views.py
from django.views.generic import TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.eventos.models import Evento
from .models import Academia
from django.contrib.auth.views import LoginView

from apps.planes_estudiantes.models import Estudiante, InscripcionPlan, Plan
from apps.asistencias.models import Asistencia
from apps.finanzas.models import ReciboIngreso, Gasto

from django.utils import timezone
from django.db.models import Sum, Max, Prefetch
import json

from .forms import ConfigMascaraForm

from django.contrib.auth.views import LogoutView

from apps.multimedia.models import VideoClase

from django.contrib.auth.views import PasswordChangeView
from django.contrib import messages
from django.urls import reverse_lazy
from apps.saas_core.models import ConfigPagoGlobalSaaS

from .mixins import *

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
            
        # 2. TRAER EVENTOS Y PRE-CALCULAR PASES (🚀 LÓGICA SENIOR)
        try:
            eventos = Evento.objects.filter(
                academia=academia_activa,
                fecha__gte=timezone.now(),  
                estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
            ).order_by('fecha')[:6]
            
            now = timezone.now()
            
            for evt in eventos:
                fase_activa = None
                # Si tiene fases, buscamos la que está vigente hoy
                if evt.tiene_fases_fechas:
                    fase_activa = evt.fases_preventa.filter(fecha_limite__gte=now).order_by('fecha_limite').first()
                    if not fase_activa:
                        fase_activa = evt.fases_preventa.order_by('-fecha_limite').first()
                
                # Armamos un diccionario con los precios finales a mostrar
                pases_info = []
                for pase in evt.pases_personalizados.all():
                    precio_final = pase.precio
                    if fase_activa:
                        pivote = fase_activa.precios_pases.filter(pase=pase).first()
                        if pivote and pivote.precio is not None:
                            precio_final = pivote.precio
                    
                    pases_info.append({
                        'nombre': pase.nombre,
                        'precio': precio_final,
                        'accesos': pase.accesos_permitidos
                    })
                
                # Inyectamos esta data temporalmente al objeto del evento para usarla en el HTML
                evt.pases_procesados = pases_info
                evt.fase_actual = fase_activa.nombre_fase if fase_activa else None
                
            context['eventos'] = eventos
        except Exception:
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
    """Formulario de inicio de sesión adaptado al tenant con control anti-morosos."""
    template_name = "academias/login.html"

    def get_success_url(self):
        """🚀 REDIRECCIÓN INTELIGENTE: Evalúa si el inquilino está suspendido antes de dar paso."""
        user = self.request.user
        tenant = self.request.tenant
        slug = tenant.slug
        suscripcion = tenant.suscripcion_saas

        # 🛑 FILTRO DE CONTROL SAAS: Si la academia está bloqueada/suspendida
        if suscripcion.estado == 'SUSPENDIDO':
            # Si es un estudiante, no debería usar la plataforma; si es admin, va directo a la pantalla de cobro
            # Redirigimos a una ruta segura que maneje el aviso (por ejemplo, la landing page o la URL capturada por el middleware)
            return reverse('academias:dashboard', kwargs={'slug_academia': slug})

        try:
            perfil = user.perfil
            # 1. Si es Administrador o Profesor, va al panel de control global
            if perfil.rol in ['ADMIN_ACADEMIA', 'PROFESOR']:
                return reverse('academias:dashboard', kwargs={'slug_academia': slug})
            
            # 2. 🎯 Si es Estudiante, va DIRECTO a su portal de tiqueteras y QR
            elif perfil.rol == 'ESTUDIANTE':
                return reverse('planes_estudiantes:portal_estudiante', kwargs={'slug_academia': slug})
        
        except AttributeError:
            # Si es un Superusuario maestro de Django, al dashboard por defecto
            if user.is_staff:
                return reverse('academias:dashboard', kwargs={'slug_academia': slug})
        
        return reverse('academias:index', kwargs={'slug_academia': slug})



class DashboardAdminView(TenantAdminRequiredMixin, TemplateView):
    """Renderiza el panel de control administrativo de la academia específica."""
    template_name = "academias/dashboard.html"

    def get(self, request, *args, **kwargs):
        """Intercepta la petición GET para evitar procesar contexto si la cuenta está en mora."""
        academia = self.request.tenant
        suscripcion = academia.suscripcion_saas
        
        # ⚡ CORTOCIRCUITO MAESTRO: Si la academia está suspendida, congelamos el backend aquí
        if suscripcion.estado == 'SUSPENDIDO':
            datos_pago = ConfigPagoGlobalSaaS.objects.first()
            
            # Renderizamos directamente la plantilla de bloqueo, ignorando por completo todo el código de abajo
            return render(request, 'academias/bloqueado_pago.html', {
                'academia': academia,
                'suscripcion': suscripcion,
                'datos_pago': datos_pago,
                'monto_a_pagar': suscripcion.plan.precio_mensual
            }, status=403)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        # Este método ya SOLO se ejecutará si la academia está ACTIVA y AL DÍA.
        context = super().get_context_data(**kwargs)
        academia = self.request.tenant
        context['academia'] = academia
        
        suscripcion = academia.suscripcion_saas
        context['es_partner'] = suscripcion.es_cuenta_partner_gratis

        # 📅 MANEJO DE FECHAS
        ahora = timezone.localtime(timezone.now())
        año_actual, mes_actual = ahora.year, ahora.month
        hoy_fecha = ahora.date()
        
        año_anterior = año_actual - 1 if mes_actual == 1 else año_actual
        mes_anterior = 12 if mes_actual == 1 else mes_actual - 1

        # 👥 KPI DE ESTUDIANTES Y EVENTOS
        context['eventos_activos'] = Evento.objects.filter(
            academia=academia, estado__in=['REGISTRO_ONLINE', 'REGISTRO_PUERTA']
        ).order_by('fecha')[:5]

        context['estudiantes_totales'] = Estudiante.objects.filter(academia=academia).count()
        context['estudiantes_activos'] = Estudiante.objects.filter(academia=academia, estado='ACTIVO').count()
        context['asistencias_hoy'] = Asistencia.objects.filter(academia=academia, fecha_hora__date=hoy_fecha).count()

        # 💵 KPI FINANCIEROS
        ingresos_mes = ReciboIngreso.objects.filter(
            academia=academia, estado='ACTIVO',
            fecha__gte=ahora.replace(day=1, hour=0, minute=0, second=0)
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        gastos_mes = Gasto.objects.filter(
            academia=academia, estado='ACTIVO', 
            fecha__year=año_actual, fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0

        context['ingresos_mes'] = ingresos_mes
        context['utilidad_mes'] = ingresos_mes - gastos_mes

        # 📊 AUDITORÍA MAESTRA (Cajas)
        caja_efectivo = ReciboIngreso.objects.filter(
            academia=academia, estado='ACTIVO', medio_pago='EFECTIVO', 
            fecha__year=año_actual, fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0
        
        caja_transferencia = ReciboIngreso.objects.filter(
            academia=academia, estado='ACTIVO', medio_pago='TRANSFERENCIA', 
            fecha__year=año_actual, fecha__month=mes_actual
        ).aggregate(total=Sum('monto'))['total'] or 0

        context['caja_efectivo'] = caja_efectivo
        context['caja_transferencia'] = caja_transferencia

        total_cajas = caja_efectivo + caja_transferencia
        context['porcentaje_efectivo'] = (caja_efectivo / total_cajas * 100) if total_cajas > 0 else 0
        context['porcentaje_transferencia'] = (caja_transferencia / total_cajas * 100) if total_cajas > 0 else 0

        # Alumnos en riesgo... (Mantenemos tu lógica intacta sin tocar nada)
        hace_7_dias = ahora - timezone.timedelta(days=7)
        estudiantes_activos = Estudiante.objects.filter(
            academia=academia, estado='ACTIVO'
        ).annotate(
            ultima_asistencia=Max('asistencias__fecha_hora')
        ).prefetch_related(
            Prefetch('inscripciones', queryset=InscripcionPlan.objects.order_by('-id'))
        )

        lista_alumnos_riesgo = []
        for est in estudiantes_activos:
            if (est.ultima_asistencia and est.ultima_asistencia < hace_7_dias) or \
               (not est.ultima_asistencia and est.fecha_registro.date() < hace_7_dias.date()):
                
                est.ultima_asistencia_str = est.ultima_asistencia.strftime('%d/%m/%Y') if est.ultima_asistencia else "Nunca ha asistido"
                planes_alumno = list(est.inscripciones.all())
                est.plan_nombre = planes_alumno[0].plan.nombre if planes_alumno else "Sin Plan Activo"
                lista_alumnos_riesgo.append(est)

        context['alumnos_en_riesgo_lista'] = lista_alumnos_riesgo
        context['alumnos_en_riesgo'] = len(lista_alumnos_riesgo)

        # Planes por vencer...
        dentro_de_5_dias = hoy_fecha + timezone.timedelta(days=5)
        context['planes_por_vencer_lista'] = InscripcionPlan.objects.filter(
            academia=academia, fecha_fin__gte=hoy_fecha, fecha_fin__lte=dentro_de_5_dias
        ).select_related('estudiante', 'plan')
        context['planes_por_vencer'] = context['planes_por_vencer_lista'].count()

        # Comparativa analítica...
        ingresos_mes_anterior = ReciboIngreso.objects.filter(
            academia=academia, estado='ACTIVO', fecha__year=año_anterior, fecha__month=mes_anterior
        ).aggregate(total=Sum('monto'))['total'] or 0
        context['comparativa_ingresos'] = round(((ingresos_mes - ingresos_mes_anterior) / ingresos_mes_anterior) * 100, 1) if ingresos_mes_anterior > 0 else 100.0

        # Gráficos Chart.js...
        datos_ingresos = ReciboIngreso.objects.filter(
            academia=academia, estado='ACTIVO', fecha__year=año_actual
        ).values('fecha__month').annotate(total=Sum('monto'))
        datos_gastos = Gasto.objects.filter(
            academia=academia, estado='ACTIVO', fecha__year=año_actual
        ).values('fecha__month').annotate(total=Sum('monto'))

        chart_ingresos = [float(next((d['total'] for d in datos_ingresos if d['fecha__month'] == m), 0)) for m in range(1, 13)]
        chart_gastos = [float(next((d['total'] for d in datos_gastos if d['fecha__month'] == m), 0)) for m in range(1, 13)]

        context['chart_ingresos'] = json.dumps(chart_ingresos)
        context['chart_gastos'] = json.dumps(chart_gastos)

        return context


# apps/academias/views.py

class BrandingConfigView(TenantAdminRequiredMixin, UpdateView):
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
    

class CambioPasswordView(TenantAccessMixin, PasswordChangeView):
    """Vista segura para que el usuario cambie su contraseña."""
    template_name = "academias/cambio_password.html"

    def get_success_url(self):
        # Generamos un mensaje de éxito que se mostrará en el dashboard
        messages.success(self.request, "¡Tu contraseña ha sido actualizada con éxito y de forma segura!")
        
        # Redirigimos al dashboard del tenant actual
        return reverse('academias:dashboard', kwargs={'slug_academia': self.request.tenant.slug})