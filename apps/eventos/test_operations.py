import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.academias.models import Academia, TenantMembership
from apps.academias.private_media import validate_private_upload
from apps.saas_core.models import AuditEvent, DurableJob
from apps.saas_core.jobs import claim, run_one
from .models import Evento, TipoPase, CodigoDescuento, ReciboEvento, Admission, EntradaQR, CheckIn, EventRefund
from .operations import register, confirm, cancel, check_in, reissue, record_refund, quote, complete_door_sale, resend_tickets
from .receipt_access import receipt_token, receipt_url


class EventOperationsTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings = override_settings(PRIVATE_MEDIA_ROOT=self.media.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.addCleanup(self.media.cleanup)
        self.tenant = Academia.objects.create(nombre='Operaciones', slug='operaciones')
        self.owner = User.objects.create_user('owner')
        TenantMembership.objects.create(user=self.owner, academia=self.tenant, role='OWNER')
        self.event = Evento.unfiltered_objects.create(academia=self.tenant, nombre='Social', fecha=timezone.now())
        self.pass_ = TipoPase.objects.create(evento=self.event, nombre='Pareja', precio=100,
            admissions_per_unit=2, qrs_por_pase=2, accesos_permitidos=2)
        self.values = {'comprador_nombre': 'Comprador de prueba', 'cantidad_entradas': 1,
                       'comprador_telefono': 'test', 'monto_total': '1'}

    def sale(self, **kwargs):
        return register(self.event, self.values, key=kwargs.pop('key', uuid.uuid4()),
                        pass_input='PASE_' + str(self.pass_.pk), **kwargs)

    def test_admin_dashboard_counts_auto_accepted_receipts_and_rejects_missing_csrf(self):
        from django.test import Client
        pending = self.sale()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('eventos:admin_detalle', args=[self.tenant.slug, self.event.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ingresos_totales'], Decimal('100'))
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        url = reverse('eventos:resend_tickets', args=[self.tenant.slug, self.event.slug, pending.pk])
        self.assertEqual(strict.post(url, {'reason': 'test'}).status_code, 403)
        confirm(pending, self.owner, 'Verificado')
        response = self.client.get(reverse('eventos:admin_detalle', args=[self.tenant.slug, self.event.slug]))
        self.assertEqual(response.context['ingresos_totales'], Decimal('100'))

    def test_event_metrics_keep_pending_registrations_visible_without_inflating_revenue(self):
        pending = self.sale()
        cancelled = self.sale()
        # Simula los comprobantes pendientes creados por la versión anterior.
        ReciboEvento.objects.filter(pk__in=[pending.pk, cancelled.pk]).update(
            payment_status='PENDING', revisado_por_admin=False, confirmed_at=None,
        )
        pending.refresh_from_db()
        cancelled.refresh_from_db()
        self.client.force_login(self.owner)
        url = reverse('eventos:admin_detalle', args=[self.tenant.slug, self.event.slug])
        listing_url = reverse('eventos:admin_lista', args=[self.tenant.slug])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_registros'], 2)
        self.assertEqual(response.context['personas_registradas'], 4)
        self.assertEqual(response.context['inscripciones_pendientes'], 2)
        self.assertEqual(response.context['personas_pendientes'], 4)
        self.assertEqual(response.context['monto_pendiente'], Decimal('200'))
        self.assertEqual(response.context['total_entradas_vendidas'], 0)
        self.assertEqual(response.context['ingresos_totales'], 0)
        pass_metrics = response.context['metricas_pases'].get(pk=self.pass_.pk)
        self.assertEqual(pass_metrics.total_registrados, 4)
        self.assertEqual(pass_metrics.total_pendientes, 4)
        self.assertEqual(pass_metrics.total_vendidos, 0)
        # El listado espera una suscripción SaaS; la creamos solo para esta prueba.
        from apps.saas_core.models import SuscripcionAcademia
        today = timezone.localdate()
        SuscripcionAcademia.objects.get_or_create(
            academia=self.tenant,
            defaults={'fecha_inicio': today, 'fecha_vencimiento': today,
                      'es_cuenta_partner_gratis': True},
        )
        listing = self.client.get(listing_url)
        summary = listing.context['eventos_activos'].get(pk=self.event.pk)
        self.assertEqual(summary.personas_registradas, 4)
        self.assertEqual(summary.personas_pendientes, 4)
        self.assertEqual(summary.boletas_vendidas, 0)

        confirm(pending, self.owner, 'Comprobante revisado')
        response = self.client.get(url)
        self.assertEqual(response.context['personas_registradas'], 4)
        self.assertEqual(response.context['personas_pendientes'], 2)
        self.assertEqual(response.context['total_entradas_vendidas'], 2)
        self.assertEqual(response.context['ingresos_totales'], Decimal('100'))
        self.assertEqual(response.context['monto_pendiente'], Decimal('100'))
        pass_metrics = response.context['metricas_pases'].get(pk=self.pass_.pk)
        self.assertEqual(pass_metrics.total_registrados, 4)
        self.assertEqual(pass_metrics.total_pendientes, 2)
        self.assertEqual(pass_metrics.total_vendidos, 2)

        cancel(cancelled, self.owner, 'Registro duplicado')
        response = self.client.get(url)
        self.assertEqual(response.context['total_registros'], 1)
        self.assertEqual(response.context['personas_registradas'], 2)
        self.assertEqual(response.context['personas_pendientes'], 0)
        self.assertEqual(response.context['total_entradas_vendidas'], 2)
        self.assertEqual(response.context['ingresos_totales'], Decimal('100'))

    def test_event_metrics_include_general_registrations_without_pass(self):
        general = Evento.unfiltered_objects.create(
            academia=self.tenant, nombre='General', fecha=timezone.now()
        )
        ReciboEvento.objects.create(
            evento=general, comprador_nombre='Registro sin pase',
            comprador_telefono='123', cantidad_entradas=3,
            precio_unitario_aplicado=Decimal('20'), monto_total=Decimal('60'),
            revisado_por_admin=False, payment_status='PENDING',
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse(
            'eventos:admin_detalle', args=[self.tenant.slug, general.slug]
        ))
        self.assertEqual(response.context['personas_registradas'], 3)
        self.assertEqual(response.context['personas_pendientes'], 3)
        self.assertEqual(response.context['general_registrados'], 3)
        self.assertEqual(response.context['general_pendientes'], 3)
        self.assertEqual(response.context['general_vendidos'], 0)
        self.assertEqual(response.context['ingresos_totales'], 0)

    def test_registration_activates_access_and_is_idempotent(self):
        key = uuid.uuid4()
        receipt = self.sale(key=key)
        self.assertEqual(receipt.monto_total, Decimal('100'))
        self.assertTrue(receipt.revisado_por_admin)
        self.assertEqual(receipt.payment_status, 'CONFIRMED')
        self.assertEqual(Admission.objects.count(), 2)
        self.assertEqual(EntradaQR.objects.count(), 2)
        code = receipt.boletas_qr.first().codigo_unico
        self.assertEqual(check_in(self.event, self.owner, code).result, 'SUCCESS')
        self.assertEqual(self.sale(key=key).pk, receipt.pk)
        confirm(receipt, self.owner, 'Comprobante validado')
        confirm(receipt, self.owner, 'Reintento')
        self.assertEqual(ReciboEvento.objects.count(), 1)
        self.assertEqual(Admission.objects.count(), 2)
        self.assertEqual(EntradaQR.objects.count(), 2)
        self.assertEqual(DurableJob.objects.filter(kind='EVENT_QR').count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='event.registration.auto_accepted').count(), 1)

    def test_public_success_displays_pending_qr_immediately_without_a_worker(self):
        receipt = self.sale()
        self.assertFalse(receipt.boletas_qr.first().imagen_qr)
        response = self.client.get(receipt_url(receipt))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data:image/png;base64,')
        self.assertContains(response, 'Tus códigos QR ya están activos')
        self.assertEqual(
            self.client.get(reverse('eventos:registro_exito', args=[self.tenant.slug, receipt.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(receipt_url(receipt).split('?')[0] + '?token=forged').status_code,
            403,
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_registration_delivers_active_qrs_by_email_without_manual_confirmation(self):
        self.values['comprador_correo'] = 'comprador@example.com'
        with self.captureOnCommitCallbacks(execute=True):
            receipt = self.sale()
        job = DurableJob.objects.get(dedupe_key=f'event-ticket-email:{receipt.pk}:CONFIRMED:first')
        self.assertEqual(job.state, 'DONE')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['comprador@example.com'])
        self.assertIn('Tu pago ya está confirmado', mail.outbox[0].body)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        self.assertEqual(mail.outbox[0].attachments[0][2], 'image/png')
        self.assertEqual(receipt.payment_status, 'CONFIRMED')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_resend_repairs_missing_qrs_and_emails_without_waiting_for_images(self):
        receipt = self.sale()
        receipt.comprador_correo = 'comprador@example.com'
        receipt.save(update_fields=['comprador_correo'])
        receipt.boletas_qr.all().delete()
        self.assertFalse(receipt.boletas_qr.exists())
        with self.captureOnCommitCallbacks(execute=True):
            resend_tickets(receipt, self.owner)
        receipt.refresh_from_db()
        self.assertEqual(receipt.payment_status, 'CONFIRMED')
        self.assertEqual(receipt.boletas_qr.count(), 2)
        self.assertTrue(all(not ticket.imagen_qr for ticket in receipt.boletas_qr.all()))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Tus entradas', mail.outbox[0].subject)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        self.assertEqual(DurableJob.objects.filter(
            dedupe_key__startswith=f'event-ticket-email:{receipt.pk}:RECOVERED:',
            state='DONE',
        ).count(), 1)
        confirm(receipt, self.owner, 'Sin segunda operación')
        self.assertEqual(DurableJob.objects.filter(
            dedupe_key__startswith=f'event-ticket-email:{receipt.pk}:RECOVERED:',
        ).count(), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_failed_immediate_email_remains_in_durable_retry_queue(self):
        self.values['comprador_correo'] = 'comprador@example.com'
        with patch('apps.eventos.tickets.EmailMultiAlternatives.send', side_effect=OSError('SMTP unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                receipt = self.sale()
        job = DurableJob.objects.get(dedupe_key=f'event-ticket-email:{receipt.pk}:CONFIRMED:first')
        self.assertEqual(job.state, 'PENDING')
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.last_error, 'OSError')
        self.assertGreater(job.available_at, timezone.now())

    def test_door_sale_registers_first_entry_and_preserves_next_day_access(self):
        key = uuid.uuid4()
        receipt = complete_door_sale(
            self.event, self.values, key=key,
            pass_input=f'PASE_{self.pass_.pk}', actor=self.owner,
        )
        receipt.refresh_from_db()
        self.assertEqual(receipt.payment_status, 'CONFIRMED')
        self.assertTrue(receipt.ingresado_puerta)
        self.assertEqual(receipt.boletas_qr.count(), 2)
        self.assertEqual(
            list(receipt.boletas_qr.values_list('asistencias_consumidas', flat=True)), [1, 1],
        )
        self.assertEqual(CheckIn.objects.filter(result='SUCCESS').count(), 2)
        first = receipt.boletas_qr.order_by('pk').first()
        self.assertEqual(check_in(self.event, self.owner, first.codigo_unico).result, 'ALREADY_USED_TODAY')
        with patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(days=1)):
            self.assertEqual(check_in(self.event, self.owner, first.codigo_unico).result, 'SUCCESS')
        self.assertEqual(
            complete_door_sale(self.event, self.values, key=key,
                               pass_input=f'PASE_{self.pass_.pk}', actor=self.owner).pk,
            receipt.pk,
        )
        self.assertEqual(ReciboEvento.objects.count(), 1)
        self.assertEqual(CheckIn.objects.filter(result='SUCCESS').count(), 3)
        with patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(days=2)):
            complete_door_sale(self.event, self.values, key=key,
                               pass_input=f'PASE_{self.pass_.pk}', actor=self.owner)
        # The same purchase is not a new check-in on day 3.
        self.assertEqual(CheckIn.objects.filter(result='SUCCESS').count(), 3)

    def test_commercial_units_do_not_reduce_personal_qr_allocation(self):
        self.pass_.admissions_per_unit = 1
        self.pass_.save(update_fields=['admissions_per_unit'])
        snapshot = quote(self.event, f'PASE_{self.pass_.pk}', 1)['snapshot']
        self.assertEqual(snapshot['access_units'], 2)
        self.assertEqual(snapshot['commercial_units'], 1)
        receipt = self.sale()
        self.assertEqual(receipt.boletas_qr.count(), 2)
        self.assertEqual(
            receipt.admissions.filter(commercial_unit=True).count(), 1,
        )

    def test_inactive_default_pass_does_not_block_general_registration(self):
        self.event.tiene_pases_personalizados = False
        self.event.precio_preventa = Decimal('50')
        self.event.save()
        self.pass_.activo = False
        self.pass_.save(update_fields=['activo'])
        self.assertEqual(quote(self.event, 'FULL', 1)['snapshot']['total'], '50.00')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_manual_resend_repairs_existing_credential_and_sends_again(self):
        receipt = self.sale()
        confirm(receipt, self.owner, 'Verified')
        receipt.comprador_correo = 'comprador@example.com'
        receipt.save(update_fields=['comprador_correo'])
        qr = receipt.boletas_qr.first()
        original_code = qr.codigo_unico
        qr.admission = None
        qr.save(update_fields=['admission'])
        with self.captureOnCommitCallbacks(execute=True):
            resend_tickets(receipt, self.owner)
        qr.refresh_from_db()
        self.assertEqual(qr.codigo_unico, original_code)
        self.assertIsNotNone(qr.admission_id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_verified_historical_registration_without_qrs_can_be_recovered_safely(self):
        legacy = ReciboEvento.objects.create(
            evento=self.event, comprador_nombre='Venta antigua',
            comprador_correo='historico@example.com', comprador_telefono='123',
            cantidad_entradas=1, precio_unitario_aplicado=Decimal('100'),
            monto_total=Decimal('100'), tipo_pase=self.pass_,
            payment_status='LEGACY', revisado_por_admin=True,
        )
        self.assertFalse(legacy.boletas_qr.exists())
        with self.captureOnCommitCallbacks(execute=True):
            resend_tickets(legacy, self.owner)
        self.assertEqual(legacy.boletas_qr.count(), 2)
        self.assertEqual(legacy.admissions.filter(commercial_unit=True).count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        self.assertEqual(legacy.payment_status, 'LEGACY')

    def test_unverified_historical_qr_is_not_accepted_at_the_door(self):
        legacy = ReciboEvento.objects.create(
            evento=self.event, comprador_nombre='Sin verificar', comprador_telefono='123',
            precio_unitario_aplicado=Decimal('100'), monto_total=Decimal('100'),
            payment_status='LEGACY', revisado_por_admin=False,
        )
        ticket = EntradaQR.objects.create(recibo=legacy)
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'PENDING_PAYMENT')
        legacy.revisado_por_admin = True
        legacy.save(update_fields=['revisado_por_admin'])
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'SUCCESS')

    def test_invalid_commercial_configuration_cannot_undercount_saas_units(self):
        self.pass_.admissions_per_unit = 3
        self.pass_.save(update_fields=['admissions_per_unit'])
        with self.assertRaises(ValidationError):
            quote(self.event, f'PASE_{self.pass_.pk}', 1)

    def test_quote_is_server_authoritative_and_snapshot_does_not_change(self):
        receipt = self.sale()
        TipoPase.objects.filter(pk=self.pass_.pk).update(precio=999)
        receipt.refresh_from_db()
        self.assertEqual(receipt.price_snapshot['total'], '100.00')
        self.assertEqual(receipt.monto_total, Decimal('100'))

    def test_foreign_pass_and_finalized_sales_are_rejected(self):
        other = Evento.unfiltered_objects.create(academia=self.tenant, nombre='Otro', fecha=timezone.now())
        with self.assertRaises(ValidationError):
            quote(other, 'PASE_' + str(self.pass_.pk), 1)
        self.event.estado = 'FINALIZADO'
        self.event.save()
        with self.assertRaises(ValidationError):
            self.sale()
        self.assertFalse(ReciboEvento.objects.exists())

    def test_confirmed_coupon_remains_consumed_when_cancelled_without_refund(self):
        coupon = CodigoDescuento.objects.create(evento=self.event, nombre_codigo='ULTIMO', precio_especial=50,
            limite_usos=1, fecha_caducidad=timezone.now() + timedelta(days=1))
        receipt = self.sale(coupon_text='ULTIMO')
        with self.assertRaises(ValidationError):
            self.sale(coupon_text='ULTIMO')
        cancel(receipt, self.owner, 'Duplicado solicitado')
        cancel(receipt, self.owner, 'Reintento')
        coupon.refresh_from_db()
        self.assertEqual(coupon.usos_actuales, 1)
        self.assertEqual(EventRefund.objects.count(), 0)

    def test_checkin_repeat_same_day_then_next_day_and_reissue(self):
        receipt = self.sale()
        confirm(receipt, self.owner, 'Verificado')
        ticket = receipt.boletas_qr.first()
        key = uuid.uuid4()
        attempt = check_in(self.event, self.owner, ticket.codigo_unico, request_key=key)
        self.assertEqual(attempt.result, 'SUCCESS')
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico, request_key=key).pk, attempt.pk)
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'ALREADY_USED_TODAY')
        old_code = ticket.codigo_unico
        reissue(ticket, self.owner, 'Credencial comprometida')
        with self.assertRaises(ValidationError):
            check_in(self.event, self.owner, old_code)
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'ALREADY_USED_TODAY')
        tomorrow = timezone.now() + timedelta(days=1)
        with patch('django.utils.timezone.now', return_value=tomorrow):
            self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'SUCCESS')
        ticket.refresh_from_db()
        self.assertEqual(ticket.asistencias_consumidas, 2)
        self.assertEqual(Admission.objects.count(), 2)
        self.assertEqual(CheckIn.objects.filter(result='SUCCESS').count(), 2)

    def test_cancel_revokes_without_inventing_refund(self):
        receipt = self.sale()
        confirm(receipt, self.owner, 'Verificado')
        ticket = receipt.boletas_qr.first()
        cancel(receipt, self.owner, 'Anulación autorizada')
        self.assertEqual(check_in(self.event, self.owner, ticket.codigo_unico).result, 'REVOKED')
        self.assertFalse(EventRefund.objects.exists())
        self.assertEqual(ReciboEvento.objects.count(), 1)

    def test_actual_refund_requires_evidence_and_is_idempotent(self):
        receipt = self.sale()
        confirm(receipt, self.owner, 'Verificado')
        refund = record_refund(receipt, self.owner, amount=100, reference='bank-proof-1', reason='Devolución realizada')
        self.assertEqual(record_refund(receipt, self.owner, amount=100, reference='bank-proof-1', reason='Reintento').pk, refund.pk)
        receipt.refresh_from_db()
        self.assertEqual(receipt.payment_status, 'REFUNDED')
        self.assertEqual(EventRefund.objects.count(), 1)

    def test_private_receipt_requires_permission_and_file_validation(self):
        with self.assertRaises(ValidationError):
            validate_private_upload(SimpleUploadedFile('fake.png', b'<script>bad</script>'))
        buffer = BytesIO()
        Image.new('RGB', (2, 2)).save(buffer, format='PNG')
        upload = SimpleUploadedFile('receipt.png', buffer.getvalue(), 'image/png')
        validate_private_upload(upload)
        self.assertFalse(upload.closed)
        self.values['comprobante_pago'] = upload
        receipt = self.sale()
        url = receipt.comprobante_pago.url
        self.assertTrue(url.startswith('/private-media/'))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content))

    def test_outbox_recovers_leases_and_caps_crashes(self):
        now = timezone.now()
        exhausted = DurableJob.objects.create(kind='EMAIL', dedupe_key='exhausted', payload={},
            state='PROCESSING', attempts=5, lease_until=now-timedelta(seconds=1))
        recover = DurableJob.objects.create(kind='EMAIL', dedupe_key='recover', payload={},
            state='PROCESSING', attempts=1, lease_until=now-timedelta(seconds=1))
        self.assertEqual(claim().pk, recover.pk)
        exhausted.refresh_from_db()
        self.assertEqual(exhausted.state, 'FAILED')
