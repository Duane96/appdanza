from django.core.management.base import BaseCommand
from apps.saas_core.models import BillingAccount
from apps.saas_core.billing import update_dunning

class Command(BaseCommand):
    help = 'Compatibilidad cron: evalúa únicamente contratos comerciales aceptados.'
    def handle(self, *args, **kwargs):
        for account in BillingAccount.objects.filter(mode='PAID').select_related('academia'):
            update_dunning(account.academia)
        self.stdout.write('Estados comerciales evaluados; exenciones preservadas.')
