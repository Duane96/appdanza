# apps/asistencias/views.py
from django.views.generic import TemplateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from apps.planes_estudiantes.models import Estudiante, InscripcionPlan
from apps.academias.mixins import TenantAdminRequiredMixin
from .models import Asistencia

class PanelEscanerView(TenantAdminRequiredMixin, TemplateView):
    template_name = "asistencias/escaner.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Traemos todos los estudiantes de la academia actual para el select
        context['estudiantes'] = Estudiante.objects.filter(academia=self.request.tenant)
        return context


class ProcesarEscaneoQRView(TenantAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return process_attendance(request, 'QR')


class ProcesarAsistenciaManualView(TenantAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        return process_attendance(request, 'MANUAL')


def process_attendance(request, mode):
    import json
    from django.core.exceptions import ValidationError
    from django.db import OperationalError
    from .operations import mark
    try:
        data = json.loads(request.body)
        student, remaining, message = mark(request.tenant, request.user,
            student_id=data.get('estudiante_id') if mode == 'MANUAL' else None,
            token=data.get('token') if mode == 'QR' else None, mode=mode)
        return JsonResponse({'status': 'success', 'estudiante': str(student),
                             'clases_restantes': remaining, 'mensaje': message})
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse({'status': 'error', 'mensaje': '; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Solicitud inválida.'}, status=400)
    except OperationalError:
        return JsonResponse({'status': 'error', 'mensaje': 'La operación está ocupada. Intenta nuevamente.'}, status=503)
