# apps/saas_core/management/commands/actualizar_estados_saas.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.saas_core.models import SuscripcionAcademia
from django.db import transaction

class Command(BaseCommand):
    help = 'Automatiza el cambio de estado (MORA o SUSPENDIDO) de las academias según su fecha de vencimiento.'

    def handle(self, *args, **kwargs):
        # 1. Obtenemos la fecha actual exacta en Colombia
        hoy_colombia = timezone.localtime(timezone.now()).date()
        
        # 2. Filtramos cuentas que debemos auditar (Excluimos las que ya están suspendidas o son Partner VIP)
        suscripciones_a_revisar = SuscripcionAcademia.objects.exclude(
            estado='SUSPENDIDO'
        ).exclude(
            es_cuenta_partner_gratis=True
        )

        cont_mora = 0
        cont_bloqueadas = 0

        self.stdout.write(self.style.WARNING(f"Iniciando auditoría de suscripciones ({hoy_colombia})..."))

        # 3. Iniciamos una transacción segura en BD
        with transaction.atomic():
            for sub in suscripciones_a_revisar:
                # Calculamos la diferencia en días
                dias_restantes = (sub.fecha_vencimiento - hoy_colombia).days

                # CASO A: Período de Prueba Vencido (Pasa directo a SUSPENDIDO, no hay mora en pruebas)
                if sub.estado == 'PRUEBA' and dias_restantes < 0:
                    sub.estado = 'SUSPENDIDO'
                    sub.save()
                    cont_bloqueadas += 1
                    self.stdout.write(self.style.ERROR(f"❌ [BLOQUEO PRUEBA]: {sub.academia.nombre}"))
                    continue

                # CASO B: Cliente Activo entra en los 5 días de Gracia (MORA)
                # Si los días están entre -1 y -5
                if sub.estado == 'ACTIVO' and -5 <= dias_restantes < 0:
                    sub.estado = 'MORA'
                    sub.save()
                    cont_mora += 1
                    self.stdout.write(self.style.NOTICE(f"⚠️ [ENTRA EN MORA]: {sub.academia.nombre} ({dias_restantes} días)"))
                    continue

                # CASO C: Cliente en Mora superó los 5 días de Gracia (CORTE TOTAL)
                if sub.estado in ['ACTIVO', 'MORA'] and dias_restantes < -5:
                    sub.estado = 'SUSPENDIDO'
                    sub.save()
                    cont_bloqueadas += 1
                    self.stdout.write(self.style.ERROR(f"🚫 [CORTE POR MORA]: {sub.academia.nombre} (Vencido hace {abs(dias_restantes)} días)"))

        # Mensaje final para el Log del servidor
        self.stdout.write(self.style.SUCCESS(
            f"✅ Auditoría completada con éxito. {cont_mora} pasaron a MORA, {cont_bloqueadas} pasaron a SUSPENDIDO."
        ))