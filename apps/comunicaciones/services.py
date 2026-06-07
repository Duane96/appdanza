import threading
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

class HiloCorreo(threading.Thread):
    def __init__(self, asunto, html_content, destinatarios, adjunto=None):
        self.asunto = asunto
        self.html_content = html_content
        self.destinatarios = destinatarios
        self.adjunto = adjunto # Nuevo parámetro
        threading.Thread.__init__(self)

    def run(self):
        msg = EmailMultiAlternatives(
            subject=self.asunto,
            body="Por favor, visualiza este correo en un cliente que soporte HTML.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=self.destinatarios
        )
        msg.attach_alternative(self.html_content, "text/html")
        
        # 📎 Si recibimos un adjunto, lo pegamos al correo
        if self.adjunto:
            # adjunto debe ser una tupla: ('nombre_archivo.pdf', bytes_del_archivo, 'application/pdf')
            msg.attach(self.adjunto['nombre'], self.adjunto['contenido'], self.adjunto['mimetype'])
            
        try:
            msg.send()
        except Exception as e:
            print(f"Error enviando correo a {self.destinatarios}: {e}")

def enviar_correo_transaccional(asunto, template_name, context, destinatarios, adjunto=None):
    html_content = render_to_string(template_name, context)
    HiloCorreo(asunto, html_content, destinatarios, adjunto).start()