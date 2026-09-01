# apps/eventos/management/commands/cerrar_eventos_vencidos.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.eventos.models import Evento

class Command(BaseCommand):
    help = 'Busca eventos cuya fecha ya pasó, los finaliza y liquida la comisión del SaaS.'

    def handle(self, *args, **kwargs):
        ahora = timezone.now()
        
        # 1. Buscamos eventos que NO estén finalizados
        eventos_abiertos = Evento.objects.exclude(estado='FINALIZADO')
        eventos_cerrados_hoy = 0

        for evento in eventos_abiertos:
            debe_cerrarse = False
            
            # 2. Lógica de vencimiento
            if evento.es_multidias and evento.fecha_fin:
                # Si es multidía, se cierra 1 día después de la fecha de fin
                if ahora > (evento.fecha_fin + timedelta(days=1)):
                    debe_cerrarse = True
            else:
                # Si es de un solo día, se cierra 2 días después de la fecha de inicio
                if ahora > (evento.fecha + timedelta(days=2)):
                    debe_cerrarse = True
            
            # 3. Ejecutamos el cierre y congelamos deuda
            if debe_cerrarse:
                evento.congelar_deuda_y_finalizar()
                eventos_cerrados_hoy += 1
                self.stdout.write(self.style.SUCCESS(f"✅ Cerrado y liquidado: {evento.nombre} (ID: {evento.id})"))

        self.stdout.write(self.style.WARNING(f"🚀 Tarea completada. Eventos cerrados hoy: {eventos_cerrados_hoy}"))