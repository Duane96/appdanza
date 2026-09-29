from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from apps.saas_core.models import PaymentAttempt
from apps.saas_core.epayco import reconcile_reference, ProviderError


class Command(BaseCommand):
    help = 'Consulta ePayco sin cobrar; recupera intentos inciertos con referencia verificable.'

    def add_arguments(self, parser):
        parser.add_argument('--reference')
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=10)
        PaymentAttempt.objects.filter(state='SUBMITTING', updated_at__lt=cutoff).update(
            state='UNKNOWN', failure_code='interrupted_request', updated_at=timezone.now())
        refs = [options['reference']] if options['reference'] else list(PaymentAttempt.objects.filter(
            state__in=('PENDING', 'UNKNOWN')).exclude(provider_reference='').order_by('created_at')
            .values_list('provider_reference', flat=True)[:max(0, options['limit'])])
        processed = review = 0
        for reference in refs:
            try:
                result = reconcile_reference(reference)
            except ProviderError:
                raise CommandError('No se pudo consultar ePayco. No se realizó ningún cobro.')
            processed += result.state == 'PROCESSED'
            review += result.state == 'REVIEW'
        unknown = PaymentAttempt.objects.filter(state='UNKNOWN', provider_reference='').count()
        self.stdout.write(f'Conciliados: {processed}; revisión: {review}; sin referencia: {unknown}. Sin nuevos cobros.')
