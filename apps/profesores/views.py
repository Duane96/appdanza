from apps.saas_core.entitlement_guards import creation_guard
from django.views.generic import CreateView, ListView
from django.views import View
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.models import User
from django.db import transaction
from django.contrib import messages

from apps.academias.mixins import TenantAdminRequiredMixin
from .models import Profesor
from apps.academias.models import PerfilUsuario
from .forms import ProfesorForm

# Añade esto al final de apps/profesores/views.py
from django.views.generic import TemplateView
from apps.academias.mixins import TenantAccessMixin

from django.views.generic import TemplateView
from django.db.models import Count, Avg, Sum, Q
from django.utils import timezone
import datetime
from apps.academias.mixins import TenantAccessMixin
from apps.calendario.models import SesionClase
from apps.finanzas.models import Gasto
from .models import OrdenPagoMensual

import json
from django.http import JsonResponse

from decimal import Decimal

class DashboardProfesorView(TenantAccessMixin, TemplateView):
    """
    Pantalla de inicio exclusiva para el Profesor.
    Implementa un 'Carrito de Compras' estricto: Las cuentas enviadas o en revisión
    jamás se modifican. Solo se agrupan las clases libres.
    """
    template_name = "profesores/dashboard_profesor.html"

    def post(self, request, *args, **kwargs):
        from .operations import prepare
        from django.core.exceptions import ValidationError
        try:
            prepare(request.tenant, request.user)
            messages.success(request, 'Cuenta preparada para revisión.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        return redirect('profesores:dashboard_profesor', slug_academia=request.tenant.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            profesor = self.request.user.perfil_profesor
        except AttributeError:
            context['profesor'] = None
            return context

        tenant = self.request.tenant
        ahora = timezone.localtime(timezone.now())
        fecha_hoy = ahora.date()

        inicio_semana = ahora - datetime.timedelta(days=ahora.weekday())
        inicio_semana = inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)

        filtro_profe = Q(profesor_asignado=profesor, profesor_reemplazo__isnull=True) | Q(profesor_reemplazo=profesor)

        proxima_clase = SesionClase.objects.filter(
            clase__academia=tenant, estado='PROGRAMADA', fecha_hora_inicio__gt=ahora
        ).filter(filtro_profe).select_related('clase').order_by('fecha_hora_inicio').first()

        tarifa_proxima = proxima_clase.tarifa_a_pagar if proxima_clase else 0

        clases_semana = SesionClase.objects.filter(
            clase__academia=tenant, estado='DICTADA', fecha_hora_inicio__gte=inicio_semana, fecha_hora_inicio__lte=ahora
        ).filter(filtro_profe).count()

        stats_alumnos = SesionClase.objects.filter(
            clase__academia=tenant, estado='DICTADA'
        ).filter(filtro_profe).annotate(num_reservas=Count('reservas')).aggregate(promedio=Avg('num_reservas'))
        promedio_alumnos = stats_alumnos['promedio'] or 0

        dinero_pagado = 0
        dinero_pendiente = 0
        orden_actual = None

        # ==============================================================
        # 🚀 LÓGICA FINANCIERA BLINDADA (CARRITO ESTRICTO)
        # ==============================================================
        if profesor.tipo_pago == 'MENSUAL':

            # 1. DEUDA TOTAL (Suma de toda cuenta que exista y no esté pagada)
            ordenes_pendientes = OrdenPagoMensual.objects.filter(
                profesor=profesor, academia=tenant
            ).exclude(estado='PAGADA').order_by('fecha_creacion')

            dinero_pendiente = sum(o.monto_total for o in ordenes_pendientes)

            # GET is a read-only projection; preparing an order is an explicit POST.
            orden_actual = ordenes_pendientes.filter(estado='GENERADA').first() or ordenes_pendientes.last()
            free_sessions = SesionClase.objects.filter(clase__academia=tenant, estado='DICTADA',
                pagada_al_profesor=False, orden_pago_mensual=None).filter(filtro_profe)
            dinero_pendiente += sum((Decimal(str(s.tarifa_a_pagar or 0)) for s in free_sessions), Decimal('0'))

            # 5. DINERO PAGADO RECIENTE
            pagado_reciente = OrdenPagoMensual.objects.filter(
                profesor=profesor, academia=tenant, estado='PAGADA',
                fecha_actualizacion__year=ahora.year, fecha_actualizacion__month=ahora.month
            ).aggregate(total=Sum('monto_total'))
            dinero_pagado = pagado_reciente['total'] or 0

        else:
            # --- LÓGICA POR CLASE (Sin alteraciones) ---
            gastos = Gasto.objects.filter(
                academia=tenant, proveedor_nit=profesor.documento_identidad,
                categoria='NOMINA', estado='ACTIVO', fecha__year=ahora.year, fecha__month=ahora.month
            ).aggregate(total=Sum('monto'))
            dinero_pagado = gastos['total'] or 0

            sesiones_pendientes = SesionClase.objects.filter(
                clase__academia=tenant, estado='DICTADA', pagada_al_profesor=False
            ).filter(filtro_profe)
            dinero_pendiente = sum(s.tarifa_a_pagar for s in sesiones_pendientes)

        context.update({
            'profesor': profesor, 'proxima_clase': proxima_clase, 'tarifa_proxima': tarifa_proxima,
            'clases_semana': clases_semana, 'promedio_alumnos': promedio_alumnos,
            'dinero_pagado': dinero_pagado, 'dinero_pendiente': dinero_pendiente,
            'orden_actual': orden_actual, 'ahora': ahora
        })
        return context

# --- NUEVA VISTA AJAX PARA PROCESAR EL COBRO ---
class ProcesarCuentaCobroView(TenantAccessMixin, View):
    """
    Recibe la decisión del profesor sobre su planilla mensual.
    """
    def post(self, request, *args, **kwargs):
        from .operations import decide
        from django.core.exceptions import ValidationError
        try:
            data = json.loads(request.body)
            decide(request.tenant, request.user, data.get('orden_id'), data.get('accion'), data.get('observacion', ''))
            return JsonResponse({'status': 'success', 'message': 'Cuenta actualizada.'})
        except (ValueError, TypeError, ValidationError):
            return JsonResponse({'status': 'error', 'message': 'La cuenta o la acción no están disponibles.'}, status=400)


class CrearProfesorView(TenantAdminRequiredMixin, CreateView):
    """
    Vista para que el Admin registre a un profesor.
    Crea el User, el PerfilUsuario y el Profesor en una sola transacción segura.
    """
    model = Profesor
    form_class = ProfesorForm
    template_name = "profesores/crear_profesor.html"

    @creation_guard('profesores', 'max_teachers')
    def form_valid(self, form):
        nombre = form.cleaned_data['nombre']
        apellido = form.cleaned_data['apellido']
        # Extraemos el documento para pasarlo al User como password
        documento = form.cleaned_data['documento_identidad']

        base_username = f"{nombre}{apellido}".replace(" ", "").lower()
        username = base_username
        contador = 1

        while User.objects.filter(username=username).exists():
            username = f"{base_username}{contador}"
            contador += 1

        with transaction.atomic():
            # A) Creamos el usuario con el documento como contraseña
            user = User.objects.create_user(
                username=username,
                first_name=nombre,
                last_name=apellido,
                email=form.cleaned_data['email'],
                password=None
            )

            # B) PerfilUsuario
            PerfilUsuario.objects.create(
                user=user,
                academia=self.request.tenant,
                rol='PROFESOR'
            )

            # C) Guardamos el Profesor
            profesor = form.save(commit=False)
            profesor.usuario = user
            profesor.academia = self.request.tenant
            profesor.save()
            from apps.academias.invitations import invite_new_account
            invite_new_account(user, self.request.tenant, base_url=self.request.build_absolute_uri('/'), actor=self.request.user)

        messages.success(self.request, f"Profesor creado. Su usuario es: {username}")
        return super().form_valid(form)

    def get_success_url(self):
        """
        Le indica a Django a dónde redirigir al administrador después
        de haber creado al profesor exitosamente.
        """
        # Redirigimos a la lista de profesores de ESTA academia en particular
        return reverse('profesores:lista', kwargs={'slug_academia': self.request.tenant.slug})


class ListaProfesoresView(TenantAdminRequiredMixin, ListView):
    """
    Renderiza la tabla del panel admin con TODOS los profesores de la academia (activos e inactivos).
    """
    model = Profesor
    template_name = "profesores/lista_profesores.html"
    context_object_name = "profesores"

    def get_queryset(self):
        # 🛡️ FILTRADO MULTI-TENANT ESTRICTO
        # Quitamos el activo=True para traerlos todos.
        # Ordenamos por '-activo' para que los activos salgan de primeros, y luego por fecha.
        return Profesor.objects.filter(
            academia=self.request.tenant
        ).select_related('usuario').order_by('-activo', '-fecha_registro')


# Añade esta NUEVA vista al final de tu archivo:
class ActivarProfesorView(TenantAdminRequiredMixin, View):
    """
    Endpoint (vía POST) para reactivar a un profesor y devolverle el acceso al sistema.
    """
    def post(self, request, pk, *args, **kwargs):
        profesor = get_object_or_404(Profesor, pk=pk, academia=request.tenant)

        # 1. Activamos el perfil de profesor
        profesor.activo = True
        profesor.save()

        # 2. 🔓 DESBLOQUEO DE ACCESO: Le devolvemos el acceso al sistema (Login)
        user = profesor.usuario
        user.is_active = True
        user.save()

        messages.success(
            request,
            f"¡El profesor {user.get_full_name()} ha sido reactivado y ya puede acceder al sistema!"
        )
        return redirect('profesores:lista', slug_academia=request.tenant.slug)


class DesactivarProfesorView(TenantAdminRequiredMixin, View):
    """
    Endpoint (vía POST) para desactivar a un profesor sin borrar su historial financiero.
    """
    def post(self, request, pk, *args, **kwargs):
        # 1. Buscamos al profe asegurando que pertenezca a ESTE tenant
        profesor = get_object_or_404(Profesor, pk=pk, academia=request.tenant)

        # 2. Desactivamos el perfil de profesor
        profesor.activo = False
        profesor.save()

        # 3. 🛑 BLOQUEO DE ACCESO: Le quitamos el acceso al sistema (Login)
        user = profesor.usuario
        user.is_active = False
        user.save()

        messages.success(
            request,
            f"El profesor {user.get_full_name()} ha sido desactivado. Su historial financiero se mantiene intacto."
        )
        return redirect('profesores:lista', slug_academia=request.tenant.slug)




class PagarCuentaCobroAdminView(TenantAdminRequiredMixin, View):
    """
    Endpoint AJAX para que el administrador pague una cuenta de cobro aprobada.
    Genera el egreso en Finanzas automáticamente.
    """
    def post(self, request, *args, **kwargs):
        from .operations import pay
        from django.core.exceptions import ValidationError
        try:
            data = json.loads(request.body)
            pay(request.tenant, request.user, data.get('orden_id'))
            return JsonResponse({'status': 'success', 'message': 'Pago registrado en Finanzas.'})
        except (ValueError, TypeError, ValidationError):
            return JsonResponse({'status': 'error', 'message': 'La cuenta no está disponible para pago.'}, status=400)
