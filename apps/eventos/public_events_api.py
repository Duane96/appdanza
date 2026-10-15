"""Read-only agenda of upcoming public events, for DyA Social Studio's chat assistant.

Exposes only what each academy's public page already shows (name, date, place, city,
prices, registration link, poster). Never receipts, buyers, contacts, payments or
expenses. Same bearer token as the DyA integration; GET only; HTTPS in production.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Evento

PUBLIC_STATES = ('REGISTRO_ONLINE', 'REGISTRO_PUERTA')
MAX_EVENTS = 50


def _absolute(path):
    return settings.APPDANZA_PUBLIC_URL.rstrip('/') + path


def event_row(event):
    if event.enlace_externo:
        registration = event.enlace_externo
    elif event.estado == 'REGISTRO_ONLINE' and event.slug and event.academia.slug:
        registration = _absolute(reverse('eventos:registro_publico', kwargs={
            'slug_academia': event.academia.slug, 'evento_slug': event.slug}))
    else:
        registration = ''
    image = ''
    if event.imagen:
        try:
            image = _absolute(event.imagen.url)
        except ValueError:
            image = ''
    return {
        'id': event.pk,
        'name': event.nombre,
        'start': event.fecha.isoformat(),
        'end': event.fecha_fin.isoformat() if event.fecha_fin else None,
        'place': event.ubicacion,
        'city': getattr(event, 'ciudad', '') or event.academia.ciudad or '',
        'state': event.estado,
        'registration_url': registration,
        'image_url': image,
        'price_presale': str(event.precio_preventa) if event.precio_preventa else None,
        'price_door': str(event.precio_puerta) if event.precio_puerta else None,
        'academy': {'slug': event.academia.slug, 'name': event.academia.nombre},
    }


@require_GET
def public_events(request):
    token = settings.DYA_INTEGRATION_API_TOKEN
    supplied = request.headers.get('Authorization', '')
    if not token or not secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return JsonResponse({'error': 'unauthorized'}, status=401)
    if not settings.DEBUG and not request.is_secure():
        return JsonResponse({'error': 'https_required'}, status=403)
    # Events that started up to 6 h ago are still "tonight's event".
    since = timezone.now() - timedelta(hours=6)
    queryset = (Evento.unfiltered_objects.filter(academia__activo=True, estado__in=PUBLIC_STATES, fecha__gte=since)
                .select_related('academia').order_by('fecha', 'pk'))
    academy = (request.GET.get('academy') or '').strip()
    if academy:
        queryset = queryset.filter(academia__slug__in=[s for s in academy.split(',') if s][:10])
    rows = [event_row(event) for event in queryset[:MAX_EVENTS]]
    response = JsonResponse({'schema_version': 1, 'kind': 'public_agenda', 'events': rows})
    response['Cache-Control'] = 'no-store'
    return response
