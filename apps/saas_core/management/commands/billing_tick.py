from django.core.management.base import BaseCommand
from apps.saas_core.billing_scheduler import tick


class Command(BaseCommand):
    help = 'Evaluate accepted contracts, dunning and configured payment attempts; exemptions always win.'

    def handle(self, *args, **kwargs):
        tick()
        self.stdout.write('Billing cycle evaluated.')
