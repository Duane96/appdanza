# apps/comunicaciones/management/commands/probar_correos.py
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

# Importamos los modelos reales
from apps.academias.models import Academia
from apps.planes_estudiantes.models import Estudiante
from apps.eventos.models import Evento

class Command(BaseCommand):
    help = 'Envía correos de prueba usando datos REALES de la base de datos de una academia.'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, nargs='?', default='dduane.abreu@gmail.com')
        # Permite cambiar el slug desde la consola si en el futuro quieres probar otra
        parser.add_argument('--slug', type=str, default='academia-prueba', help='Slug del tenant')

    def enviar_sync(self, asunto, template, context, destinatario):
        html_content = render_to_string(template, context)
        msg = EmailMultiAlternatives(
            subject=asunto,
            body="Por favor, visualiza este correo en un cliente que soporte HTML.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[destinatario]
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        self.stdout.write(self.style.SUCCESS(f'✅ Enviado: {asunto} a {destinatario}'))

    def handle(self, *args, **options):
        email_destino = options['email']
        slug_target = options['slug']
        
        self.stdout.write(f"Iniciando extracción de datos para Tenant: '{slug_target}'...\n")

        # 1. TRAER LA ACADEMIA REAL
        try:
            # Usamos unfiltered_objects en caso de que tengas managers personalizados
            academia = Academia.unfiltered_objects.get(slug=slug_target)
        except Academia.DoesNotExist:
            try:
                academia = Academia.objects.get(slug=slug_target)
            except Academia.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"❌ ERROR: No existe ninguna academia con el slug '{slug_target}'."))
                return

        # 2. TRAER 2 ESTUDIANTES REALES Y ENVIAR RECIBOS
        estudiantes = Estudiante.objects.filter(academia=academia)[:2]
        
        if not estudiantes.exists():
            self.stdout.write(self.style.WARNING("⚠️ La academia no tiene estudiantes. Saltando prueba de recibos..."))
        else:
            for i, estudiante in enumerate(estudiantes, start=1):
                context_recibo = {
                    'academia': academia, # 🚀 Objeto REAL
                    'estudiante': estudiante, # 🚀 Objeto REAL
                    # Simulamos la transacción contable
                    'recibo': {'numero_recibo': f'RC-TEST-00{i}', 'monto': '145.000'},
                    'plan': {'nombre': 'Tiquetera Full Access (Prueba)'},
                    'fecha_fin': (timezone.now() + timezone.timedelta(days=30)).strftime('%d/%m/%Y'),
                    'portal_url': f'https://tu-saas.com/{academia.slug}/portal/'
                }
                self.enviar_sync(
                    asunto=f"Tu recibo de pago en {academia.nombre}",
                    template="comunicaciones/recibo_plan.html",
                    context=context_recibo,
                    destinatario=email_destino
                )

        # 3. TRAER EVENTO REAL Y ENVIAR TICKETS CON QR
        evento = Evento.objects.filter(academia=academia).first()
        
        if not evento:
            self.stdout.write(self.style.WARNING("⚠️ La academia no tiene eventos creados. Saltando prueba de QR..."))
        else:
            # Simulamos 2 boletas generadas para este evento
            boletas_simuladas = [
                {
                    'codigo': f'EV-{evento.id}-X9A1', 
                    'qr_url': f'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=EV-{evento.id}-X9A1'
                },
                {
                    'codigo': f'EV-{evento.id}-Z4B2', 
                    'qr_url': f'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=EV-{evento.id}-Z4B2'
                }
            ]
            
            context_evento = {
                'academia': academia, # 🚀 Objeto REAL
                'comprador_nombre': 'Socio Senior',
                'evento': evento, # 🚀 Objeto REAL
                'boletas': boletas_simuladas
            }
            self.enviar_sync(
                asunto=f"🎟️ Tus entradas para {evento.nombre}",
                template="comunicaciones/ticket_evento.html",
                context=context_evento,
                destinatario=email_destino
            )

        self.stdout.write(self.style.SUCCESS('\n🎉 ¡Extracción y envío finalizados! Revisa tu bandeja de entrada.'))