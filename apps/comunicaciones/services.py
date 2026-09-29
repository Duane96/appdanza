"""Render and persist email; delivery is handled by the durable worker."""
import base64
from django.template.loader import render_to_string
from apps.saas_core.jobs import enqueue


def enviar_correo_transaccional(asunto, template_name, context, destinatarios, adjunto=None):
    payload = {'subject': asunto, 'html': render_to_string(template_name, context), 'to': destinatarios}
    if adjunto:
        payload['attachment'] = {'name': adjunto['nombre'], 'type': adjunto['mimetype'],
                                 'data': base64.b64encode(adjunto['contenido']).decode('ascii')}
    return enqueue('EMAIL', payload, tenant=context.get('academia'))
def queue_mail(subject, message, from_email=None, recipient_list=None, html_message=None, fail_silently=False, **kwargs):
    from apps.saas_core.jobs import enqueue
    return enqueue('EMAIL', {'subject': subject, 'text': message, 'to': recipient_list or [],
                             'html': html_message or ''})
