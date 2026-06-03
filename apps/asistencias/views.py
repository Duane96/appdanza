# apps/asistencias/views.py
from django.views.generic import TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
from .models import Asistencia

class PanelEscanerView(LoginRequiredMixin, TemplateView):
    template_name = "asistencias/escaner.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Traemos todos los estudiantes de la academia actual para el select
        context['estudiantes'] = Estudiante.objects.filter(academia=self.request.tenant)
        return context


class ProcesarEscaneoQRView(LoginRequiredMixin, View):
    """API asíncrona que procesa el token escaneado del QR."""
    
    def post(self, request, *args, **kwargs):
        import json
        try:
            data = json.loads(request.body)
            token = data.get('token')
            
            # 1. Validamos que el estudiante exista en la academia actual
            estudiante = Estudiante.objects.get(token_asistencia=token, academia=request.tenant)
            
            # 🚀 EL CERROJO DE BACKEND: Evitar doble marcado en menos de 2 minutos
            hace_dos_minutos = timezone.now() - timezone.timedelta(minutes=1)
            asistencia_reciente = Asistencia.objects.filter(
                estudiante=estudiante,
                academia=request.tenant,
                fecha_hora__gte=hace_dos_minutos
            ).exists()

            if asistencia_reciente:
                return JsonResponse({
                    'status': 'error',
                    'mensaje': f"Marcado duplicado: {estudiante.nombres} ya registró su asistencia hace un momento."
                }, status=400) # Devolvemos error 400 (Bad Request)

            # 2. Buscamos si tiene un plan activo vigente
            hoy = timezone.now().date()
            inscripcion = InscripcionPlan.objects.filter(
                estudiante=estudiante,
                fecha_inicio__lte=hoy,
                fecha_fin__gte=hoy,
                clases_restantes__gt=0
            ).first()

            if not inscripcion:
                estudiante.estado = 'INACTIVO'
                estudiante.save()
                return JsonResponse({
                    'status': 'error', 
                    'mensaje': f"Acceso Denegado: {estudiante.nombres} no tiene un plan activo o se le acabaron las clases."
                }, status=400)

            # 3. Si todo está en orden, registramos la asistencia
            Asistencia.objects.create(
                academia=request.tenant,
                estudiante=estudiante,
                tipo_marcado='QR',
                registrado_por=request.user
            )

            # 4. Descontamos una clase de su tiquetera
            inscripcion.clases_restantes -= 1
            inscripcion.save()

            if inscripcion.clases_restantes == 0:
                estudiante.estado = 'INACTIVO'
                estudiante.save()

            return JsonResponse({
                'status': 'success',
                'estudiante': f"{estudiante.nombres} {estudiante.apellidos}",
                'clases_restantes': inscripcion.clases_restantes,
                'mensaje': "¡Ingreso Autorizado con éxito!"
            })

        except Estudiante.DoesNotExist:
            return JsonResponse({'status': 'error', 'mensaje': 'Código QR no válido o de otra academia.'}, status=404)
        except Exception as e:
            print("❌ ERROR CRÍTICO EN LA API DE QR:")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'error', 'mensaje': f'Error interno: {str(e)}'}, status=500)
        

class ProcesarAsistenciaManualView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        import json
        data = json.loads(request.body)
        estudiante_id = data.get('estudiante_id')
        
        try:
            estudiante = Estudiante.objects.get(id=estudiante_id, academia=request.tenant)
            
            # Reutilizamos la misma lógica de validación de plan activo que en el QR
            hoy = timezone.now().date()
            inscripcion = InscripcionPlan.objects.filter(
                estudiante=estudiante, fecha_inicio__lte=hoy, fecha_fin__gte=hoy, clases_restantes__gt=0
            ).first()

            if not inscripcion:
                return JsonResponse({'status': 'error', 'mensaje': 'El estudiante no tiene plan activo.'}, status=400)

            # Registrar asistencia
            Asistencia.objects.create(
                academia=request.tenant, estudiante=estudiante, tipo_marcado='MANUAL', registrado_por=request.user
            )
            
            # Descontar clase
            inscripcion.clases_restantes -= 1
            inscripcion.save()

            return JsonResponse({'status': 'success', 'estudiante': f"{estudiante.nombres} {estudiante.apellidos}", 'clases_restantes': inscripcion.clases_restantes})

        except Estudiante.DoesNotExist:
            return JsonResponse({'status': 'error', 'mensaje': 'Estudiante no encontrado.'}, status=404)