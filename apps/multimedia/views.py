# apps/multimedia/views.py
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.contrib import messages
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView

from .models import ModuloClase, VideoClase
from .forms import VideoClaseForm, ModuloClaseForm

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


class VisorClaseView(View):
    """Vista para el estudiante: Muestra el reproductor y las lecciones."""
    def get(self, request, slug_academia, modulo_id):
        # Aseguramos el aislamiento Multi-Tenant interceptando el request.tenant
        # Traemos el módulo evaluando de forma estricta que pertenezca a la academia actual.
        modulo = get_object_or_404(ModuloClase, id=modulo_id, academia=request.tenant)
        
        # OPTIMIZACIÓN DJANGO PRO: Traemos todos los videos ordenados de una sola vez
        # Usamos prefetch_related o simplemente evaluamos el query en memoria para evitar llamadas dobles
        videos = list(modulo.videos.all().order_by('fecha_subida'))
        
        # Extraemos el primer video directamente de nuestra lista en memoria de Python
        primer_video = videos[0] if len(videos) > 0 else None
        
        context = {
            'modulo': modulo,
            'videos': videos,  # Pasamos la lista precalculada al contexto
            'primer_video': primer_video,
            'slug_academia': slug_academia
        }
        return render(request, 'multimedia/visor.html', context)


class ListaModulosAdminView(LoginRequiredMixin, ListView):
    model = ModuloClase
    template_name = "multimedia/admin_lista_clases.html"
    context_object_name = 'modulos'

    def get_queryset(self):
        return ModuloClase.objects.filter(academia=self.request.tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug_actual = self.kwargs.get('slug_academia')
        context['slug_academia'] = slug_actual
        context['slug'] = slug_actual
        return context


class CrearModuloAdminView(LoginRequiredMixin, CreateView):
    model = ModuloClase
    form_class = ModuloClaseForm
    template_name = "multimedia/admin_form_clase.html"

    def form_valid(self, form):
        form.instance.academia = self.request.tenant
        messages.success(self.request, "¡Clase/Módulo creado con éxito!")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug_actual = self.kwargs.get('slug_academia')
        context['slug_academia'] = slug_actual
        context['slug'] = slug_actual
        return context

    def get_success_url(self):
        return reverse_lazy('multimedia:lista_clases_admin', kwargs={'slug_academia': self.request.tenant.slug})


@method_decorator(csrf_exempt, name='dispatch')
class SubirVideoAdminView(LoginRequiredMixin, View):
    def get(self, request, slug_academia):
        form = VideoClaseForm(academia=request.tenant)
        return render(request, 'multimedia/admin_subir_video.html', {'form': form, 'slug_academia': slug_academia})

    def post(self, request, slug_academia):
        # Capturamos datos del POST
        video_id = request.POST.get("video_id")
        
        # Validamos que el ID de YouTube venga presente
        if not video_id:
            return JsonResponse({'status': 'error', 'message': 'Falta el ID de YouTube.'}, status=400)

        form = VideoClaseForm(request.POST, academia=request.tenant)
        
        if form.is_valid():
            video = form.save(commit=False)
            video.youtube_id = video_id  # Asignamos el ID de YouTube
            video.save()
            return JsonResponse({'status': 'success', 'message': 'Video guardado correctamente.'})
        
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)