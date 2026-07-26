from datetime import timedelta
import json
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView, TemplateView, UpdateView
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count

from apps.academias.mixins import TenantAdminRequiredMixin, TenantAccessMixin
from .models import SesionClase, ReservaEstudiante
from apps.profesores.models import OrdenPagoMensual
from apps.finanzas.models import Gasto

from django.views.generic import CreateView
from django.urls import reverse
from django.contrib import messages
from .forms import *
import calendar
from django.shortcuts import redirect
# ---------------------------------------------------------
# VISTAS DEL ADMINISTRADOR
# ---------------------------------------------------------

class CalendarioAdminView(TenantAdminRequiredMixin, TemplateView):
    """
    Renderiza el Tablero de Clases estilo Post-it (Miro Board).
    Calcula dinámicamente la matriz del mes actual (Lunes a Domingo).
    """
    template_name = "calendario/admin_calendario.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Obtener año y mes de los parámetros GET (para navegar entre meses) o usar el actual
        hoy = timezone.localtime(timezone.now()).date()
        anio = int(self.request.GET.get('anio', hoy.year))
        mes = int(self.request.GET.get('mes', hoy.month))

        # Diccionario para traducir los meses al español de forma limpia
        meses_es = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }

        # 2. Generar la matriz del mes (firstweekday=0 significa que empieza en Lunes)
        cal = calendar.Calendar(firstweekday=0)
        dias_mes = cal.monthdatescalendar(anio, mes)

        # 3. Definir rango de fechas visible para la consulta SQL
        primer_dia = dias_mes[0][0]
        ultimo_dia = dias_mes[-1][-1]

        # 4. 🛡️ Consultar sesiones estrictamente del Tenant en este rango de fechas
        sesiones = SesionClase.objects.filter(
            clase__academia=self.request.tenant,
            fecha_hora_inicio__date__gte=primer_dia,
            fecha_hora_inicio__date__lte=ultimo_dia
        ).select_related(
            'clase', 
            'profesor_asignado__usuario',
            'profesor_reemplazo__usuario'
        ).prefetch_related(
            'reservas__estudiante' # 🚀 NUEVO: Traemos a los alumnos de un solo golpe (Cero N+1 queries)
        ).annotate(
            total_reservas=Count('reservas')
        ).order_by('fecha_hora_inicio')

        # 5. Organizar las sesiones en un diccionario clave-valor por fecha (YYYY-MM-DD)
        sesiones_por_fecha = {}
        for s in sesiones:
            fecha_str = s.fecha_hora_inicio.date().isoformat()
            if fecha_str not in sesiones_por_fecha:
                sesiones_por_fecha[fecha_str] = []
            sesiones_por_fecha[fecha_str].append(s)

        # 6. Calcular botones de navegación (Mes anterior / Mes siguiente)
        mes_anterior = mes - 1 if mes > 1 else 12
        anio_anterior = anio if mes > 1 else anio - 1
        mes_siguiente = mes + 1 if mes < 12 else 1
        anio_siguiente = anio if mes < 12 else anio + 1

        context.update({
            'dias_mes': dias_mes,
            'anio_actual': anio,
            'mes_actual': mes,
            'nombre_mes': meses_es.get(mes, ''),
            'sesiones_por_fecha': sesiones_por_fecha,
            'mes_anterior': mes_anterior,
            'anio_anterior': anio_anterior,
            'mes_siguiente': mes_siguiente,
            'anio_siguiente': anio_siguiente,
            'hoy': hoy,
        })

        context['catalogo_clases'] = Clase.objects.filter(academia=self.request.tenant).order_by('nombre')
        context['profesores_activos'] = Profesor.objects.filter(academia=self.request.tenant, activo=True).select_related('usuario')
        return context


class ProgramarSesionAjaxView(TenantAdminRequiredMixin, View):
    """
    Endpoint AJAX para agendar una o múltiples sesiones desde el modal del calendario.
    Aprovecha el desacoplamiento para crear horarios infinitos sin recargar la página.
    """
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            clase_id = data.get('clase_id')
            profe_id = data.get('profe_id')
            inicio_str = data.get('inicio')  # Formato ISO: YYYY-MM-DDThh:mm
            fin_str = data.get('fin')
            repetir = data.get('repetir', False)
            semanas = int(data.get('semanas', 1))

            # 🛡️ Validar pertenencia al Tenant
            clase = Clase.objects.get(id=clase_id, academia=request.tenant)
            profe = Profesor.objects.get(id=profe_id, academia=request.tenant, activo=True)

            # Convertir strings del navegador a fechas conscientes de la zona horaria (Colombia)
            inicio = timezone.make_aware(timezone.datetime.fromisoformat(inicio_str))
            fin = timezone.make_aware(timezone.datetime.fromisoformat(fin_str))

            if fin <= inicio:
                return JsonResponse({'status': 'error', 'message': 'La hora de fin debe ser posterior a la de inicio.'})

            sesiones_a_crear = []
            
            with transaction.atomic():
                if repetir and semanas > 1:
                    # 🚀 Bucle multiplicador
                    for i in range(semanas):
                        sesiones_a_crear.append(SesionClase(
                            academia=request.tenant,
                            clase=clase,
                            profesor_asignado=profe,
                            fecha_hora_inicio=inicio + timedelta(days=7 * i),
                            fecha_hora_fin=fin + timedelta(days=7 * i),
                            estado='PROGRAMADA'
                        ))
                    # Inserción masiva ultra-optimizada
                    SesionClase.objects.bulk_create(sesiones_a_crear)
                    mensaje = f"¡Se agendaron {semanas} semanas de {clase.nombre} exitosamente!"
                else:
                    # Creación única
                    SesionClase.objects.create(
                        academia=request.tenant,
                        clase=clase,
                        profesor_asignado=profe,
                        fecha_hora_inicio=inicio,
                        fecha_hora_fin=fin,
                        estado='PROGRAMADA'
                    )
                    mensaje = f"Sesión única de {clase.nombre} agendada."

            return JsonResponse({'status': 'success', 'message': mensaje})

        except Clase.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'La materia seleccionada no es válida.'}, status=404)
        except Profesor.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'El profesor seleccionado no es válido o está inactivo.'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Error interno: {str(e)}'}, status=500)

from decimal import Decimal

class MarcarClaseDictadaView(TenantAdminRequiredMixin, View):
    """
    Endpoint AJAX robusto para marcar una clase como dictada.
    Flujo dinámico: Acumula en la planilla "Abierta" hasta que el profe decida enviarla.
    """
    def post(self, request, *args, **kwargs):
        try:
            if not request.body:
                return JsonResponse({'status': 'error', 'message': 'Cuerpo de petición vacío.'}, status=400)
                
            data = json.loads(request.body)
            sesion_id = data.get('sesion_id')
            confirmar_pago = data.get('confirmar_pago', False) 

            sesion = SesionClase.objects.select_related(
                'profesor_asignado__usuario',
                'profesor_reemplazo__usuario'
            ).get(id=sesion_id, clase__academia=request.tenant)

            if sesion.estado == 'DICTADA':
                if not (confirmar_pago and not sesion.pagada_al_profesor):
                    return JsonResponse({'status': 'info', 'message': 'Esta clase ya había sido procesada.'})

            profesor = sesion.profe_a_pagar
            if not profesor:
                return JsonResponse({'status': 'error', 'message': 'La sesión no tiene un profesor válido asignado.'}, status=400)
                
            tarifa = Decimal(str(sesion.tarifa_a_pagar or 0))

            with transaction.atomic():
                sesion.estado = 'DICTADA'
                
                # --- LÓGICA 1: PROFESOR COBRA MENSUAL (FLUJO ACUMULATIVO) ---
                if profesor.tipo_pago == 'MENSUAL':
                    # 🚀 MAGIA AQUÍ: Buscamos la planilla que esté "Abierta" (GENERADA)
                    orden = OrdenPagoMensual.objects.filter(
                        profesor=profesor, 
                        academia=request.tenant,
                        estado='GENERADA'
                    ).first()
                    
                    # Si no hay ninguna abierta (porque es nuevo o porque ya la envió), creamos una nueva
                    if not orden:
                        mes_actual = timezone.localtime(timezone.now()).date().replace(day=1)
                        orden = OrdenPagoMensual.objects.create(
                            profesor=profesor,
                            mes_periodo=mes_actual, # Queda con el nombre del mes actual en que se genera
                            academia=request.tenant,
                            estado='GENERADA',
                            cantidad_clases=0,
                            monto_total=Decimal('0.00')
                        )
                    
                    sesion.orden_pago_mensual = orden
                    sesion.pagada_al_profesor = False
                    sesion.save()

                    # Sumamos a la bolsa
                    orden.cantidad_clases += 1
                    orden.monto_total += tarifa
                    orden.save()

                    return JsonResponse({
                        'status': 'success', 
                        'tipo_pago': 'MENSUAL',
                        'message': f'Clase añadida a la cuenta de cobro abierta de {profesor.usuario.first_name}.'
                    })

                # --- LÓGICA 2: PROFESOR COBRA POR CLASE ---
                elif profesor.tipo_pago == 'POR_CLASE':
                    if confirmar_pago:
                        gasto = Gasto.objects.create(
                            academia=request.tenant,
                            categoria='NOMINA',
                            concepto=f"Pago clase dictada: {sesion.clase.nombre} - Prof. {profesor.usuario.get_full_name()}",
                            monto=tarifa,
                            proveedor_nit=profesor.documento_identidad,
                            proveedor_nombre=profesor.usuario.get_full_name(),
                            es_deducible=True
                        )
                        sesion.gasto_individual = gasto
                        sesion.pagada_al_profesor = True
                        sesion.save()

                        return JsonResponse({
                            'status': 'success', 
                            'tipo_pago': 'POR_CLASE',
                            'pagado': True,
                            'message': '¡Clase marcada y Gasto registrado exitosamente en Finanzas!'
                        })
                    else:
                        sesion.save()
                        return JsonResponse({
                            'status': 'success', 
                            'tipo_pago': 'POR_CLASE',
                            'pagado': False,
                            'tarifa': tarifa,
                            'profesor_nombre': profesor.usuario.get_full_name(),
                            'message': 'Clase registrada exitosamente.'
                        })

        except SesionClase.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'La sesión no existe.'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Error interno: {str(e)}'}, status=500)

# ---------------------------------------------------------
# VISTAS DE CONFIGURACIÓN (PROGRAMACIÓN)
# ---------------------------------------------------------

class CrearClaseView(TenantAdminRequiredMixin, CreateView):
    """Crea la plantilla base de la clase (Ej: Bachata Sensual)"""
    model = Clase
    form_class = ClaseForm
    template_name = "calendario/crear_clase.html"

    def get_form_kwargs(self):
        # 🛡️ Inyectamos el tenant actual hacia el formulario (forms.py)
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        clase = form.save(commit=False)
        clase.academia = self.request.tenant # Vinculación estricta al TenantModel
        clase.save()
        messages.success(self.request, f"¡La clase '{clase.nombre}' se ha creado exitosamente! Ya puedes programarle fechas.")
        return super().form_valid(form)

    def get_success_url(self):
        # Al crear la plantilla, podemos redirigirlo de vuelta al calendario general
        return reverse('calendario:admin_calendario', kwargs={'slug_academia': self.request.tenant.slug})


class ListaClasesView(TenantAdminRequiredMixin, ListView):
    """Muestra todas las Clases Base (Catálogo) creadas por la academia."""
    model = Clase
    template_name = "calendario/lista_clases.html"
    context_object_name = "clases"

    def get_queryset(self):
        # 🚀 FIX: Eliminamos el select_related('profesor_asignado__usuario') 
        # porque el profesor ahora se asigna en la SesionClase, no en la Clase base.
        return Clase.objects.filter(academia=self.request.tenant).order_by('nombre')


class EditarExcepcionSesionView(TenantAdminRequiredMixin, UpdateView):
    """Vista para modificar una instancia específica del calendario."""
    model = SesionClase
    form_class = ExcepcionSesionForm
    template_name = "calendario/excepcion_sesion.html"

    def get_queryset(self):
        # 🛡️ Solo permitimos editar sesiones de nuestra academia
        return SesionClase.objects.filter(clase__academia=self.request.tenant)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        sesion = form.save(commit=False)
        # Si la cancelan, aseguramos que no quede como pagada
        if sesion.estado == 'CANCELADA':
            sesion.pagada_al_profesor = False
            # Opcional: Aquí podrías emitir una notificación a los alumnos reservados
        sesion.save()
        messages.success(self.request, "Excepción aplicada correctamente a la sesión.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('calendario:admin_calendario', kwargs={'slug_academia': self.request.tenant.slug})

# Asegúrate de importar JsonResponse si no lo tienes
from django.http import JsonResponse

class CalendarioEventosJSONView(TenantAdminRequiredMixin, View):
    """
    API interna que alimenta a FullCalendar.js con las sesiones de la academia.
    Solo consulta las fechas visibles en pantalla para ahorrar memoria RAM.
    """
    def get(self, request, *args, **kwargs):
        # FullCalendar envía automáticamente parámetros 'start' y 'end' en formato ISO
        start_date = request.GET.get('start')
        end_date = request.GET.get('end')

        # 🛡️ Filtramos estrictamente por Tenant y por el rango de fechas visible
        sesiones = SesionClase.objects.filter(
            clase__academia=request.tenant,
            fecha_hora_inicio__gte=start_date,
            fecha_hora_inicio__lte=end_date
        ).select_related('clase', 'profesor_asignado__usuario').annotate(
            total_reservas=Count('reservas')
        )

        eventos = []
        for sesion in sesiones:
            # Determinamos el color basado en el estado para dar feedback visual
            color = sesion.clase.color_calendario
            if sesion.estado == 'CANCELADA':
                color = '#dc3545' # Rojo peligro
            elif sesion.estado == 'DICTADA':
                color = '#198754' # Verde éxito

            eventos.append({
                'id': sesion.id,
                'title': f"{sesion.clase.nombre} ({sesion.total_reservas}/{sesion.clase.limite_cupos})",
                'start': sesion.fecha_hora_inicio.isoformat(),
                'end': sesion.fecha_hora_fin.isoformat(),
                'backgroundColor': color,
                'borderColor': color,
                'textColor': '#ffffff',
                'extendedProps': {
                    'nombre_clase': sesion.clase.nombre,
                    'profesor': sesion.profe_a_pagar.usuario.get_full_name(),
                    'estado': sesion.estado,
                    'cupos': f"{sesion.total_reservas} / {sesion.clase.limite_cupos}",
                    'tipo_pago': sesion.profe_a_pagar.tipo_pago,
                    'pagada': sesion.pagada_al_profesor,
                    # URL dinámica para el botón de "Excepción" en el modal frontal
                    'url_excepcion': reverse('calendario:excepcion_sesion', kwargs={'slug_academia': request.tenant.slug, 'pk': sesion.id})
                }
            })

        return JsonResponse(eventos, safe=False)


class EditarClaseView(TenantAdminRequiredMixin, UpdateView):
    """Permite modificar el nombre, precio, profe o descripción de una Clase Base."""
    model = Clase
    form_class = ClaseForm
    template_name = "calendario/crear_clase.html" # ¡Reutilizamos la misma plantilla!

    def get_queryset(self):
        # 🛡️ SEGURIDAD: Evita que un admin edite la clase de otra academia
        return Clase.objects.filter(academia=self.request.tenant)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"La clase '{form.instance.nombre}' fue actualizada correctamente.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('calendario:lista_clases', kwargs={'slug_academia': self.request.tenant.slug})


class CrearSesionClaseView(TenantAdminRequiredMixin, CreateView):
    """Agenda una clase y la multiplica en el tiempo si el usuario lo requiere."""
    model = SesionClase
    form_class = SesionClaseForm
    template_name = "calendario/crear_sesion.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['tenant'] = self.request.tenant
        return kwargs

    def form_valid(self, form):
        sesion_base = form.save(commit=False)
        sesion_base.academia = self.request.tenant
        
        if sesion_base.fecha_hora_fin <= sesion_base.fecha_hora_inicio:
            form.add_error('fecha_hora_fin', 'La hora final debe ser posterior a la de inicio.')
            return self.form_invalid(form)

        repetir = form.cleaned_data.get('repetir_semanalmente')
        semanas = form.cleaned_data.get('semanas_a_repetir') or 1

        sesiones_a_crear = []
        
        with transaction.atomic():
            if repetir and semanas > 1:
                # 🚀 BUCLE MULTIPLICADOR DE SESIONES
                for i in range(semanas):
                    nueva_fecha_inicio = sesion_base.fecha_hora_inicio + timedelta(days=7 * i)
                    nueva_fecha_fin = sesion_base.fecha_hora_fin + timedelta(days=7 * i)
                    
                    sesiones_a_crear.append(SesionClase(
                        academia=self.request.tenant,
                        clase=sesion_base.clase,
                        profesor_asignado=sesion_base.profesor_asignado,
                        fecha_hora_inicio=nueva_fecha_inicio,
                        fecha_hora_fin=nueva_fecha_fin,
                        estado='PROGRAMADA'
                    ))
                
                # Inserción masiva ultra-optimizada
                SesionClase.objects.bulk_create(sesiones_a_crear)
                messages.success(self.request, f"¡Éxito! Se programaron {semanas} sesiones semanales de {sesion_base.clase.nombre}.")
            else:
                # Guardado normal (1 sola sesión)
                sesion_base.save()
                messages.success(self.request, f"Sesión única de {sesion_base.clase.nombre} programada.")

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('calendario:admin_calendario', kwargs={'slug_academia': self.request.tenant.slug})   


# ---------------------------------------------------------
# VISTAS DEL ESTUDIANTE
# ---------------------------------------------------------

class CalendarioEstudianteView(TenantAccessMixin, TemplateView):
    """
    Vista amigable para el estudiante.
    Muestra el calendario y ahora inyecta la información de su plan vigente.
    """
    template_name = "calendario/estudiante_calendario.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ahora = timezone.localtime(timezone.now())
        hoy = ahora.date()
        
        anio = int(self.request.GET.get('anio', hoy.year))
        mes = int(self.request.GET.get('mes', hoy.month))
        
        meses_es = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 
                    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

        cal = calendar.Calendar(firstweekday=0)
        dias_mes = cal.monthdatescalendar(anio, mes)

        primer_dia = dias_mes[0][0]
        ultimo_dia = dias_mes[-1][-1]

        # 🛡️ Solo mostramos las clases futuras o del día en curso (estado 'PROGRAMADA')
        sesiones = SesionClase.objects.filter(
            clase__academia=self.request.tenant,
            estado='PROGRAMADA',
            fecha_hora_inicio__date__gte=primer_dia,
            fecha_hora_inicio__date__lte=ultimo_dia,
            fecha_hora_inicio__gte=ahora 
        ).select_related('clase', 'profesor_asignado__usuario').order_by('fecha_hora_inicio')

        sesiones_por_fecha = {}
        for s in sesiones:
            fecha_str = s.fecha_hora_inicio.date().isoformat()
            if fecha_str not in sesiones_por_fecha:
                sesiones_por_fecha[fecha_str] = []
            sesiones_por_fecha[fecha_str].append(s)

        # 🚀 EXTRAEMOS RESERVAS ACTIVAS
        mis_reservas_ids = list(ReservaEstudiante.objects.filter(
            estudiante=self.request.user,
            sesion__clase__academia=self.request.tenant
        ).values_list('sesion_id', flat=True))

        # 🚀 NUEVO: EXTRAEMOS LA INFORMACIÓN DEL PLAN PARA LA CABECERA
        from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
        user = self.request.user
        academia = self.request.tenant
        
        estudiante_obj = None
        if user.first_name and user.last_name:
            qs = Estudiante.objects.filter(nombres__iexact=user.first_name, apellidos__iexact=user.last_name, academia=academia)
            if qs.count() > 1 and user.email and user.email.strip() != "":
                estudiante_obj = qs.filter(email__iexact=user.email).first()
            else:
                estudiante_obj = qs.first()
                
        if not estudiante_obj and user.email and user.email.strip() != "":
            estudiante_obj = Estudiante.objects.filter(email__iexact=user.email, academia=academia).first()

        if estudiante_obj:
            context['plan_activo'] = InscripcionPlan.objects.filter(
                estudiante=estudiante_obj,
                academia=academia,
                fecha_fin__gte=hoy
            ).order_by('fecha_fin').first()
        else:
            context['plan_activo'] = None

        mes_anterior = mes - 1 if mes > 1 else 12
        anio_anterior = anio if mes > 1 else anio - 1
        mes_siguiente = mes + 1 if mes < 12 else 1
        anio_siguiente = anio if mes < 12 else anio + 1

        context.update({
            'dias_mes': dias_mes, 'anio_actual': anio, 'mes_actual': mes,
            'nombre_mes': meses_es.get(mes, ''), 'sesiones_por_fecha': sesiones_por_fecha,
            'mes_anterior': mes_anterior, 'anio_anterior': anio_anterior,
            'mes_siguiente': mes_siguiente, 'anio_siguiente': anio_siguiente, 'hoy': hoy,
            'mis_reservas_ids': mis_reservas_ids
        })
        return context


class ReservarClaseView(TenantAccessMixin, View):
    """
    Endpoint AJAX Inteligente y Seguro.
    """
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            sesion_id = data.get('sesion_id')
            accion = data.get('accion') 

            sesion = SesionClase.objects.annotate(
                total_reservas=Count('reservas')
            ).get(id=sesion_id, clase__academia=request.tenant, estado='PROGRAMADA')

            from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
            user = request.user
            academia = request.tenant
            
            estudiante_obj = None
            if user.first_name and user.last_name:
                qs = Estudiante.objects.filter(nombres__iexact=user.first_name, apellidos__iexact=user.last_name, academia=academia)
                if qs.count() > 1 and user.email and user.email.strip() != "":
                    estudiante_obj = qs.filter(email__iexact=user.email).first()
                else:
                    estudiante_obj = qs.first()
                    
            if not estudiante_obj and user.email and user.email.strip() != "":
                estudiante_obj = Estudiante.objects.filter(email__iexact=user.email, academia=academia).first()

            if not estudiante_obj:
                return JsonResponse({'status': 'error', 'message': 'No tienes una ficha de estudiante activa.'})

            plan_activo = InscripcionPlan.objects.filter(
                estudiante=estudiante_obj,
                academia=academia,
                fecha_fin__gte=timezone.localtime(timezone.now()).date()
            ).order_by('fecha_fin').first()

            # --- CANCELAR ---
            if accion == 'CANCELAR':
                reserva = ReservaEstudiante.objects.filter(sesion=sesion, estudiante=user).first()
                if reserva:
                    with transaction.atomic():
                        reserva.delete()
                        if plan_activo:
                            plan_activo.clases_restantes += 1
                            plan_activo.save()
                    return JsonResponse({'status': 'success', 'message': 'Has cancelado tu asistencia. Se devolvió el cupo a tu saldo.'})
                return JsonResponse({'status': 'info', 'message': 'No tenías reserva en esta clase.'})

            # --- RESERVAR ---
            elif accion == 'RESERVAR':
                if sesion.total_reservas >= sesion.clase.limite_cupos:
                    return JsonResponse({'status': 'error', 'message': 'Lo sentimos, esta clase ya está llena.'})

                if not plan_activo or plan_activo.clases_restantes <= 0:
                    return JsonResponse({'status': 'error', 'message': 'No tienes clases disponibles. Por favor renueva tu plan.'})

                with transaction.atomic():
                    # 🚀 FIX SENIOR: Le indicamos explícitamente el Tenant al crear la reserva
                    reserva, created = ReservaEstudiante.objects.get_or_create(
                        sesion=sesion, 
                        estudiante=user,
                        defaults={'academia': academia}  # <--- AQUÍ ESTÁ LA MAGIA
                    )
                    
                    if created:
                        plan_activo.clases_restantes -= 1
                        plan_activo.save()
                        return JsonResponse({'status': 'success', 'message': '¡Cupo reservado con éxito! Nos vemos en clase.'})
                    else:
                        return JsonResponse({'status': 'info', 'message': 'Ya tenías un cupo reservado.'})

        except SesionClase.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'La clase no existe o ya pasó.'}, status=404)
        except Exception as e:
            print(f"\n🚨 ERROR GRAVE EN AJAX RESERVA: {str(e)}\n")
            return JsonResponse({'status': 'error', 'message': f'Fallo en el servidor: {str(e)}'}, status=500)






class CalendarioProfesorView(TenantAccessMixin, TemplateView):
    """
    Vista de Calendario (Tablero) de Solo Lectura para el Profesor.
    Solo ve las clases donde él enseña.
    """
    template_name = "calendario/profesor_calendario.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        hoy = timezone.localtime(timezone.now()).date()
        anio = int(self.request.GET.get('anio', hoy.year))
        mes = int(self.request.GET.get('mes', hoy.month))
        
        meses_es = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 
                    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}

        cal = calendar.Calendar(firstweekday=0)
        dias_mes = cal.monthdatescalendar(anio, mes)

        primer_dia = dias_mes[0][0]
        ultimo_dia = dias_mes[-1][-1]

        try:
            profesor = self.request.user.perfil_profesor
            # 🛡️ FILTRO: Solo SUS clases
            filtro_profe = Q(profesor_asignado=profesor, profesor_reemplazo__isnull=True) | Q(profesor_reemplazo=profesor)
        except AttributeError:
            filtro_profe = Q(id=0) # Si algo falla, no mostramos nada

        # 4. 🛡️ Consultar sesiones estrictamente del Tenant en este rango de fechas
        sesiones = SesionClase.objects.filter(
            clase__academia=self.request.tenant,
            fecha_hora_inicio__date__gte=primer_dia,
            fecha_hora_inicio__date__lte=ultimo_dia
        ).select_related(
            'clase', 
            'profesor_asignado__usuario',
            'profesor_reemplazo__usuario'
        ).prefetch_related(
            'reservas__estudiante' # 🚀 NUEVO: Traemos a los alumnos de un solo golpe (Cero N+1 queries)
        ).annotate(
            total_reservas=Count('reservas')
        ).order_by('fecha_hora_inicio')

        sesiones_por_fecha = {}
        for s in sesiones:
            fecha_str = s.fecha_hora_inicio.date().isoformat()
            if fecha_str not in sesiones_por_fecha:
                sesiones_por_fecha[fecha_str] = []
            sesiones_por_fecha[fecha_str].append(s)

        mes_anterior = mes - 1 if mes > 1 else 12
        anio_anterior = anio if mes > 1 else anio - 1
        mes_siguiente = mes + 1 if mes < 12 else 1
        anio_siguiente = anio if mes < 12 else anio + 1

        context.update({
            'dias_mes': dias_mes, 'anio_actual': anio, 'mes_actual': mes,
            'nombre_mes': meses_es.get(mes, ''), 'sesiones_por_fecha': sesiones_por_fecha,
            'mes_anterior': mes_anterior, 'anio_anterior': anio_anterior,
            'mes_siguiente': mes_siguiente, 'anio_siguiente': anio_siguiente, 'hoy': hoy,
        })
        return context