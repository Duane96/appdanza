"""Safeguards for the one-time active registration reconciliation."""
from decimal import Decimal
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academias.models import Academia, TenantMembership
from django.contrib.auth.models import User
from apps.saas_core.models import DurableJob
from .models import Evento, TipoPase, ReciboEvento, EntradaQR
from .operations import check_in


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ActiveRecoveryTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(nombre='Bachatamanía', slug='bachatamania-recuperacion')
        self.owner = User.objects.create_user('organizador-recuperacion')
        TenantMembership.objects.create(user=self.owner, academia=self.tenant, role='OWNER')
        self.event = Evento.unfiltered_objects.create(
            academia=self.tenant, nombre='Bachatamanía Octubre', fecha=timezone.now()
        )
        self.pass_ = TipoPase.objects.create(
            evento=self.event, nombre='Full pareja', precio=Decimal('100'),
            qrs_por_pase=2, accesos_permitidos=3,
        )

    def old_receipt(self, *, event=None, email='asistente@example.com', status='PENDING', reviewed=False):
        return ReciboEvento.objects.create(
            evento=event or self.event,
            comprador_nombre='Asistente original',
            comprador_correo=email,
            comprador_telefono='3000000000',
            cantidad_entradas=1, tipo_pase=self.pass_,
            precio_unitario_aplicado=Decimal('100'),
            monto_total=Decimal('100'),
            revisado_por_admin=reviewed,
            payment_status=status,
        )

    def test_dry_run_never_changes_database_or_sends_email(self):
        receipt = self.old_receipt()
        out = StringIO()
        call_command('normalizar_inscritos_activos', stdout=out)
        receipt.refresh_from_db()
        self.assertEqual(receipt.payment_status, 'PENDING')
        self.assertFalse(receipt.revisado_por_admin)
        self.assertFalse(receipt.boletas_qr.exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('SIMULACIÓN', out.getvalue())
        self.assertIn('Bachatamanía Octubre', out.getvalue())

    def test_apply_keeps_existing_qr_and_emails_once_even_when_rerun(self):
        receipt = self.old_receipt()
        first = EntradaQR.objects.create(recibo=receipt, asistencias_permitidas=3)
        original = first.codigo_unico
        with self.captureOnCommitCallbacks(execute=True):
            call_command('normalizar_inscritos_activos', apply=True, stdout=StringIO())
        receipt.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(receipt.payment_status, 'CONFIRMED')
        self.assertTrue(receipt.revisado_por_admin)
        self.assertEqual(receipt.boletas_qr.count(), 2)
        self.assertEqual(first.codigo_unico, original)
        self.assertIsNotNone(first.admission_id)
        self.assertEqual(first.asistencias_permitidas, 3)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        self.assertEqual(
            DurableJob.objects.filter(
                dedupe_key=f'event-ticket-email:{receipt.pk}:RECOVERED:active-events-recovery-v1'
            ).count(), 1,
        )
        self.assertEqual(check_in(self.event, self.owner, original).result, 'SUCCESS')

        with self.captureOnCommitCallbacks(execute=True):
            call_command('normalizar_inscritos_activos', apply=True, stdout=StringIO())
        self.assertEqual(receipt.boletas_qr.count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    def test_apply_skips_cancellations_finalized_and_missing_emails(self):
        cancelled = self.old_receipt(email='cancel@example.com')
        cancelled.anulado = True
        cancelled.payment_status = 'CANCELLED'
        cancelled.save(update_fields=['anulado', 'payment_status'])
        active_without_email = self.old_receipt(email='')
        other = Evento.unfiltered_objects.create(
            academia=self.tenant, nombre='Evento terminado',
            fecha=timezone.now(), estado='FINALIZADO',
        )
        closed_receipt = self.old_receipt(event=other, email='cerrado@example.com')
        with self.captureOnCommitCallbacks(execute=True):
            call_command('normalizar_inscritos_activos', apply=True, stdout=StringIO())
        cancelled.refresh_from_db()
        closed_receipt.refresh_from_db()
        active_without_email.refresh_from_db()
        self.assertEqual(cancelled.payment_status, 'CANCELLED')
        self.assertEqual(closed_receipt.payment_status, 'PENDING')
        self.assertEqual(active_without_email.payment_status, 'CONFIRMED')
        self.assertEqual(len(mail.outbox), 0)

    def test_recovered_recipient_access_is_not_open_to_other_tenants(self):
        receipt = self.old_receipt()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('normalizar_inscritos_activos', apply=True, stdout=StringIO())
        other = Academia.objects.create(nombre='Otra academia', slug='otra-recuperacion')
        self.assertNotEqual(receipt.evento.academia_id, other.pk)
        self.assertEqual(ReciboEvento.objects.filter(evento__academia=other).count(), 0)
