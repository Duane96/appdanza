# apps/planes_estudiantes/views.py
from django.views.generic import ListView, CreateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.utils import timezone
from .models import Estudiante, Plan, InscripcionPlan
from .forms import EstudianteForm, PlanForm, InscripcionPlanForm
from apps.academias.models import PerfilUsuario                 # 🚀 Importamos PerfilUsuario
from django.db import transaction                               # 🚀 Para guardar todo en un solo bloque seguro
from django.contrib.auth.models import User     
from django.http import HttpResponseRedirect # 🚀 Importamos esto para la redirección directa                # 🚀 Importamos User nativo
import unicodedata
from apps.finanzas.models import ReciboIngreso  # 🚀 IMPORTANTE: Importamos el nuevo modelo contable
from django.contrib import messages
from django.shortcuts import redirect

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from apps.comunicaciones.services import enviar_correo_transaccional

class CrearEstudianteView(LoginRequiredMixin, CreateView):
    model = Estudiante
    form_class = EstudianteForm
    template_name = "planes_estudiantes/form_estudiante.html"

    def form_valid(self, form):
        identificacion = form.cleaned_data['identificacion']
        email = form.cleaned_data['email']
        nombres = form.cleaned_data['nombres']
        apellidos = form.cleaned_data['apellidos']
        academia_actual = self.request.tenant

        # Limpiar nombres para generar el username 'pedroperez'
        nombre_limpio = "".join(nombres.split()).lower()
        apellido_limpio = "".join(apellidos.split()).lower()
        username_generado = f"{nombre_limpio}{apellido_limpio}"
        
        username_generado = "".join(
            c for c in unicodedata.normalize('NFD', username_generado)
            if unicodedata.category(c) != 'Mn'
        )

        with transaction.atomic():
            # 1. Crear el Usuario de Django
            user, created = User.objects.get_or_create(
                username=username_generado,
                defaults={
                    'email': email or '',
                    'first_name': nombres,
                    'last_name': apellidos,
                }
            )
            
            if not created:
                user, created = User.objects.get_or_create(
                    username=f"{username_generado}{identificacion[-4:]}",
                    defaults={
                        'email': email or '',
                        'first_name': nombres,
                        'last_name': apellidos,
                    }
                )

            user.set_password(identificacion)
            user.save()

            # 2. Crear el PerfilUsuario del SaaS
            PerfilUsuario.objects.get_or_create(
                user=user,
                defaults={
                    'academia': academia_actual,
                    'rol': 'ESTUDIANTE'
                }
            )

            # 3. Guardar el modelo Estudiante manualmente sin pasar por el super() rígido
            form.instance.academia = academia_actual
            self.object = form.save() # Guardamos el estudiante en la BD y lo asignamos a la vista
            
        # 🚀 CONTROL SENIOR: Redireccionamos directamente usando la función success_url limpia
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('planes_estudiantes:lista_estudiantes', kwargs={'slug_academia': self.request.tenant.slug})


class ListaEstudiantesView(LoginRequiredMixin, ListView):
    model = Estudiante
    template_name = "planes_estudiantes/lista_estudiantes.html"
    context_object_name = "estudiantes"

    def get_queryset(self):
        """🚀 CONSULTA ADVANCED: Trae los estudiantes y sus inscripciones juntas en un solo viaje a la BD"""
        return Estudiante.objects.all().prefetch_related('inscripciones__plan')


class AsignarPlanView(LoginRequiredMixin, CreateView):
    model = InscripcionPlan
    form_class = InscripcionPlanForm
    template_name = "planes_estudiantes/asignar_plan.html"

    # 🚀 NUEVO: Inyectamos el Tenant actual al formulario haciendo "match" con la variable
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # 🎯 CRÍTICO: Debe llamarse 'tenant' para que tu form.py lo pueda atrapar
        kwargs['tenant'] = self.request.tenant 
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            # 1. Guardamos la inscripción de la tiquetera
            inscripcion = form.save(commit=False)
            inscripcion.academia = self.request.tenant
            
            # Recuperamos los datos del plan para calcular clases y saldos
            plan = form.cleaned_data['plan']
            monto_pagado = form.cleaned_data['monto_pagado']
            fecha_fin_manual = form.cleaned_data['fecha_fin']
            
            inscripcion.clases_restantes = plan.clases_totales
            
            if fecha_fin_manual:
                inscripcion.fecha_fin = fecha_fin_manual
            else:
                inscripcion.fecha_fin = form.cleaned_data['fecha_inicio'] + timezone.timedelta(days=plan.duracion_dias)
            
            inscripcion.saldo_pendiente = plan.precio - monto_pagado
            inscripcion.save()

            # 2. 🚀 EXTRACCIÓN AUTOMÁTICA DE DATOS DEL ALUMNO
            alumno = inscripcion.estudiante # Aquí ya tenemos toda su ficha
            medio = form.cleaned_data.get('medio_pago', 'EFECTIVO')
            concepto_recibo = f"PAGO DE PLAN: {plan.nombre} - Alumno: {alumno.nombres} {alumno.apellidos}"

            # 3. Fabricamos el Recibo de Caja contable usando los datos nativos
            ReciboIngreso.objects.create(
                academia=self.request.tenant,
                inscripcion=inscripcion,
                tipo_ingreso='PLAN_ESTUDIANTE',
                concepto=concepto_recibo,
                monto=monto_pagado,
                medio_pago=medio,
                cliente_nit=alumno.identificacion,      # 🎯 ¡Magia! Extraído automáticamente
                cliente_nombre=f"{alumno.nombres} {alumno.apellidos}" # 🎯 Extraído automáticamente
            )

            recibo_creado = ReciboIngreso

            # 🚀 DISPARADOR DE CORREO: Recibo de Plan
            if alumno.email:
                # Construimos la URL absoluta (incluyendo https://midominio.com)
                portal_url = self.request.build_absolute_uri(
                    reverse('planes_estudiantes:portal_estudiante', kwargs={'slug_academia': self.request.tenant.slug})
                )
                
                enviar_correo_transaccional(
                    asunto=f"Tu recibo de pago en {self.request.tenant.nombre}",
                    template_name="comunicaciones/recibo_plan.html",
                    context={
                        'academia': self.request.tenant,
                        'estudiante': alumno,
                        'recibo': recibo_creado,
                        'plan': plan,
                        'fecha_fin': inscripcion.fecha_fin.strftime('%d/%m/%Y'),
                        'portal_url': portal_url
                    },
                    destinatarios=[alumno.email]
                )

            # 4. Activamos al alumno
            alumno.estado = 'ACTIVO'
            alumno.save()

        messages.success(self.request, f"Plan asignado con éxito a {alumno.nombres}. Recibo autogenerado.")
        return redirect('planes_estudiantes:lista_estudiantes', slug_academia=self.request.tenant.slug)
    


    # apps/planes_estudiantes/views.py
from django.views.generic import TemplateView
from apps.asistencias.models import Asistencia # Importamos el modelo de asistencias

# apps/planes_estudiantes/views.py

class PortalEstudianteView(LoginRequiredMixin, TemplateView):
    template_name = "planes_estudiantes/portal_estudiante.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        academia_actual = self.request.tenant

        try:
            # 1. Buscamos el estudiante por su correo electrónico
            estudiante = Estudiante.objects.get(email=user.email, academia=academia_actual)
            context['estudiante'] = estudiante

            # 2. Traemos TODAS las tiqueteras para sacar la actual, pero al contexto solo pasamos las últimas 10 para el historial de pagos
            todas_inscripciones = InscripcionPlan.objects.filter(
                estudiante=estudiante, 
                academia=academia_actual
            ).order_by('-fecha_inicio')
            
            context['pagos'] = todas_inscripciones[:10] # 🚀 LIMITADO A LOS ÚLTIMOS 10 PAGOS

            # 3. Identificamos su tiquetera/plan más reciente (el activo)
            plan_actual = todas_inscripciones.first()
            context['plan_actual'] = plan_actual

            # 4. 🧠 FILTRADO INTELIGENTE DE ASISTENCIAS:
            if plan_actual:
                # Traemos solo las asistencias desde la fecha en que inició este plan en adelante
                context['asistencias'] = Asistencia.objects.filter(
                    estudiante=estudiante,
                    academia=academia_actual,
                    fecha_hora__date__gte=plan_actual.fecha_inicio # 🚀 Solo desde que empezó el plan actual
                ).order_by('-fecha_hora')
            else:
                context['asistencias'] = Asistencia.objects.none()

        except Estudiante.DoesNotExist:
            context['error'] = "No se encontró un perfil de estudiante asociado a esta cuenta corporativa."
        
        return context
    
class CrearPlanView(LoginRequiredMixin, CreateView):
    """Permite a la academia crear nuevos planes/tiqueteras aisladas a su tenant."""
    model = Plan
    form_class = PlanForm
    template_name = "planes_estudiantes/form_plan.html"

    def form_valid(self, form):
        # 1. Asignamos la academia actual en silencio para que el usuario no tenga que elegirla
        form.instance.academia = self.request.tenant
        
        # 2. Mensaje de éxito visual para el usuario
        messages.success(self.request, f"¡Plan '{form.instance.nombre}' creado exitosamente!")
        return super().form_valid(form)

    def get_success_url(self):
        # Al terminar, lo regresamos al panel de estudiantes
        return reverse('planes_estudiantes:lista_estudiantes', kwargs={'slug_academia': self.request.tenant.slug})
    

def api_detalle_estudiante(request, slug_academia, est_id):
    est = get_object_or_404(Estudiante, id=est_id, academia__slug=slug_academia)

    # Traemos solo los últimos 10 planes por defecto para no saturar el JSON
    ultimos_planes = est.inscripciones.select_related('plan').order_by('-fecha_fin')[:10]

    # Traer últimas 5 asistencias
    asistencias = est.asistencias.all().order_by('-fecha_hora')[:5]
    
    # Preparamos los datos
    data = {
        "nombres": est.nombres,
        "apellidos": est.apellidos,
        "telefono": est.telefono,
        "email": est.email,
        "estado": est.estado,
        "qr_url": est.qr_code.url if est.qr_code else None,
        "planes": [
            {
                "nombre": p.plan.nombre,
                "fecha_fin": p.fecha_fin.strftime('%d/%m/%Y'),
                "clases": p.clases_restantes
            } for p in ultimos_planes
        ],

        "asistencias": [
            {"fecha": a.fecha_hora.strftime('%d/%m/%Y %H:%M'), "tipo": a.tipo_marcado} 
            for a in asistencias
        ],
        
        "total_planes": est.inscripciones.count() # Para mostrar si tiene más de 10
        # Aquí podrías añadir un query para traer asistencias recientes
    }
    return JsonResponse(data)