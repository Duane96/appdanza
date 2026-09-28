import json
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.academias.models import Academia
from .models import Evento, ReciboEvento, GastoEvento
from .forms import EventoForm


@override_settings(DYA_INTEGRATION_API_TOKEN='test-integration-only', DEBUG=True)
class DyAIntegrationTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(pk=3, nombre='Bachatamanía', slug='bachatamania', divisa='COP')
        self.other = Academia.objects.create(pk=4, nombre='Otra academia', slug='otra', divisa='COP')
        self.event = Evento.objects.create(academia=self.tenant, nombre='Bachatamanía Noviembre',
            fecha=timezone.now(), ubicacion='Bogotá', connect_dya_finances=True)
        self.off = Evento.objects.create(academia=self.tenant, nombre='Apagado', fecha=timezone.now(), ubicacion='Bogotá')
        self.foreign = Evento.objects.create(academia=self.other, nombre='No compartir',
            fecha=timezone.now(), ubicacion='Bogotá', connect_dya_finances=True)
        self.url = reverse('dya_events')
        self.auth = {'HTTP_AUTHORIZATION': 'Bearer test-integration-only'}

    def receipt(self, **kwargs):
        return ReciboEvento.objects.create(evento=self.event, comprador_nombre='Dato privado',
            comprador_telefono='privado', origen='PUERTA', precio_unitario_aplicado=100,
            monto_total=100, **kwargs)

    def test_missing_and_invalid_token(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION='Bearer wrong').status_code, 401)

    @override_settings(DYA_INTEGRATION_API_TOKEN='')
    def test_unconfigured_fails_closed(self):
        self.assertEqual(self.client.get(self.url, **self.auth).status_code, 401)

    def test_list_only_opted_in_tenant_and_detail_scope(self):
        result = self.client.get(self.url, **self.auth)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([e['event']['id'] for e in result.json()['events']], [self.event.pk])
        for event in (self.off, self.foreign):
            self.assertEqual(self.client.get(reverse('dya_event', args=[event.pk]), **self.auth).status_code, 404)

    def test_financial_statuses_privacy_and_aware_dates(self):
        self.receipt()
        self.receipt(anulado=True)
        self.receipt(revisado_por_admin=False)
        GastoEvento.objects.create(evento=self.event, concepto='DJ', monto=20)
        response = self.client.get(reverse('dya_event', args=[self.event.pk]), **self.auth)
        data = response.json()
        self.assertEqual(Decimal(data['income']['paid_receipts_total']), 100)
        self.assertEqual(len(data['receipts']), 3)
        self.assertEqual(len(data['expenses']), 1)
        self.assertEqual(data['refunds'], [])
        self.assertEqual(data['refund_semantics'], 'annulments_in_receipts_no_refund_ledger')
        self.assertNotIn('comprador', response.content.decode())
        self.assertNotIn('Dato privado', response.content.decode())
        self.assertNotIn('boletas_qr', response.content.decode())
        self.assertTrue(data['receipts'][0]['fecha'].endswith('Z') or '+' in data['receipts'][0]['fecha'])
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_all_mutations_rejected(self):
        for url in (self.url, reverse('dya_event', args=[self.event.pk])):
            for method in ('post', 'put', 'patch', 'delete'):
                self.assertEqual(getattr(self.client, method)(url, **self.auth).status_code, 405)
        self.assertEqual(Evento.objects.count(), 3)

    @override_settings(DEBUG=False)
    def test_production_requires_https(self):
        self.assertEqual(self.client.get(self.url, **self.auth).status_code, 403)
        self.assertEqual(self.client.get(self.url, secure=True, **self.auth).status_code, 200)

    def test_toggle_form_only_for_bachatamania(self):
        form = EventoForm(tenant=self.tenant)
        self.assertFalse(form.fields['connect_dya_finances'].initial)
        self.assertNotIn('connect_dya_finances', EventoForm(tenant=self.other).fields)
        self.assertIn('connect_dya_finances', EventoForm(instance=self.event).fields)
        self.assertNotIn('connect_dya_finances', EventoForm({'connect_dya_finances': True}, tenant=self.other).fields)

    def test_child_edits_deletes_and_annulment_change_fingerprint(self):
        def fingerprint():
            return self.client.get(self.url, **self.auth).json()['events'][0]['fingerprint']
        before = fingerprint()
        sale = self.receipt()
        self.assertNotEqual(before, fingerprint())
        before = fingerprint()
        ReciboEvento.objects.filter(pk=sale.pk).update(anulado=True)
        self.assertNotEqual(before, fingerprint())
        expense = GastoEvento.objects.create(evento=self.event, concepto='DJ', monto=20)
        before = fingerprint()
        GastoEvento.objects.filter(pk=expense.pk).update(monto=30)
        self.assertNotEqual(before, fingerprint())
        before = fingerprint()
        expense.delete()
        self.assertNotEqual(before, fingerprint())

    def test_toggle_off_removes_event(self):
        self.event.connect_dya_finances = False
        self.event.save()
        self.assertEqual(self.client.get(self.url, **self.auth).json()['events'], [])
