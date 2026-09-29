import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from apps.saas_core.jobs import run_one


class Command(BaseCommand):
    help = 'Procesa el outbox durable de AppDanza; no inicia cobros automáticos.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--duration', type=int, default=0, help='Máximo de segundos; 0 mantiene el worker activo.')
        parser.add_argument('--with-billing', action='store_true', help='Evalúa contratos y conciliación cada 300 segundos.')

    def handle(self, *args, **options):
        processed = 0
        started = time.monotonic()
        next_billing = started
        while True:
            if options['duration'] and time.monotonic() - started >= options['duration']:
                self.stdout.write(f'Processed {processed} jobs; timed worker completed.')
                break
            close_old_connections()
            if options['with_billing'] and time.monotonic() >= next_billing:
                from apps.saas_core.billing_scheduler import tick
                from django.core.management import call_command
                try:
                    tick()
                    call_command('reconcile_billing', limit=50, verbosity=0)
                except Exception as exc:
                    # No payloads, recipients, provider responses or credentials.
                    self.stderr.write('Billing evaluation requires attention: '+type(exc).__name__)
                next_billing = time.monotonic() + 300
            found = run_one()
            processed += int(found)
            if options['once'] and (not found or processed >= options['limit']):
                self.stdout.write(f'Processed {processed} jobs')
                break
            if not found:
                time.sleep(2)
