import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.academias.models import Academia, TenantMembership
from apps.academias.private_media import validate_private_upload
from apps.saas_core.models import AuditEvent, DurableJob
from apps.saas_core.jobs import claim, run_one
from .models import Evento, TipoPase, CodigoDescuento, ReciboEvento, Admission, EntradaQR, CheckIn, EventRefund
from .operations import register, confirm, cancel, check_in, reissue, record_refund, quote
from .receipt_access import receipt_token


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

    def test_admin_dashboard_excludes_pending_and_mutations_require_csrf(self):
        from django.test import Client
        pending = self.sale()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('eventos:admin_detalle', args=[self.tenant.slug, self.event.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ingresos_totales'], 0)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        url = reverse('eventos:confirm_payment', args=[self.tenant.slug, self.event.slug, pending.pk])
        self.assertEqual(strict.post(url, {'reason': 'test'}).status_code, 403)
        confirm(pending, self.owner, 'Verificado')
        response = self.client.get(reverse('eventos:admin_detalle', args=[self.tenant.slug, self.event.slug]))
        self.assertEqual(response.context['ingresos_totales'], Decimal('100'))

    def test_pending_does_not_emit_access_and_confirmation_is_idempotent(self):
        key = uuid.uuid4()
        receipt = self.sale(key=key)
        self.assertEqual(receipt.monto_total, Decimal('100'))
        self.assertFalse(receipt.revisado_por_admin)
        self.assertEqual(receipt.payment_status, 'PENDING')
        self.assertEqual(EntradaQR.objects.count(), 0)
        self.assertEqual(self.sale(key=key).pk, receipt.pk)
        confirm(receipt, self.owner, 'Comprobante validado')
        confirm(receipt, self.owner, 'Reintento')
        self.assertEqual(ReciboEvento.objects.count(), 1)
        self.assertEqual(Admission.objects.count(), 2)
        self.assertEqual(EntradaQR.objects.count(), 2)
        self.assertEqual(DurableJob.objects.filter(kind='EVENT_QR').count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='event.payment.confirmed').count(), 1)

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

    def test_coupon_last_slot_and_cancel_release_once(self):
        coupon = CodigoDescuento.objects.create(evento=self.event, nombre_codigo='ULTIMO', precio_especial=50,
            limite_usos=1, fecha_caducidad=timezone.now() + timedelta(days=1))
        receipt = self.sale(coupon_text='ULTIMO')
        with self.assertRaises(ValidationError):
            self.sale(coupon_text='ULTIMO')
        cancel(receipt, self.owner, 'Duplicado solicitado')
        cancel(receipt, self.owner, 'Reintento')
        coupon.refresh_from_db()
        self.assertEqual(coupon.usos_actuales, 0)
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
