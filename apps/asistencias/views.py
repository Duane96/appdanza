# apps/asistencias/views.py
from django.views.generic import TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
from .models import Asistencia

class PanelEscanerView(LoginRequiredMixin, TemplateView):
    """Renderiza la pantalla de la cámara del celular del profesor."""
    template_name = "asistencias/escaner.html"


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