# apps/comunicaciones/services.py
import threading
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

class HiloCorreo(threading.Thread):
    """
    Hilo en segundo plano para enviar correos sin bloquear a los Web Workers
    de PythonAnywhere. Garantiza que la página del cliente cargue rápido.
    """
    def __init__(self, asunto, html_content, destinatarios):
        self.asunto = asunto
        self.html_content = html_content
        self.destinatarios = destinatarios
        threading.Thread.__init__(self)

    def run(self):
        # Creamos el mensaje con una versión texto por defecto y la versión HTML enriquecida
        msg = EmailMultiAlternatives(
            subject=self.asunto,
            body="Por favor, visualiza este correo en un cliente que soporte HTML.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=self.destinatarios
        )
        msg.attach_alternative(self.html_content, "text/html")
        
        try:
            msg.send()
        except Exception as e:
            # Aquí podrías usar un logger en el futuro para guardar correos fallidos
            print(f"Error enviando correo a {self.destinatarios}: {e}")

def enviar_correo_transaccional(asunto, template_name, context, destinatarios):
    """
    Función maestra que usan las demás apps para despachar correos.
    Renderiza el HTML con las variables y lanza el hilo.
    """
    # 1. Renderizamos la plantilla de Django a una cadena HTML pura
    html_content = render_to_string(template_name, context)
    
    # 2. Despachamos el hilo al fondo del procesador y continuamos la ejecución normal
    HiloCorreo(asunto, html_content, destinatarios).start()