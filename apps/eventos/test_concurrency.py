"""Run with APPDANZA_TEST_DB pointing to a disposable file for SQLite races."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import SkipTest
from django.test import TransactionTestCase
from django.db import connections, connection
from django.core.exceptions import ValidationError
from apps.saas_core import test_billing
from apps.saas_core.billing import invoice_subscription, settle
from apps.saas_core.models import SaaSInvoice, SaaSPayment
from .models import CodigoDescuento, ReciboEvento, EntradaQR, CheckIn
from .operations import register, confirm, check_in


class ConcurrentOperationsTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor == 'sqlite' and 'memory' in str(connection.settings_dict['NAME']):
            raise SkipTest('Requires a file-backed SQLite test DB; see deployment test command.')
        test_billing.BillingTests.setUp(self)

    def race(self, operation):
        gate = Barrier(2)
        def run(index):
            connections.close_all()
            try:
                gate.wait(timeout=10)
                try:
                    return operation(index)
                except ValidationError:
                    return 'rejected'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, range(2)))

    def register(self, key, coupon=''):
        return register(self.event, {'comprador_nombre': 'Concurrency test', 'comprador_telefono': 'test',
            'cantidad_entradas': 1}, key=key, pass_input='PASE_'+str(self.pass_.pk), coupon_text=coupon)

    def test_same_registration_and_confirmation_emit_once(self):
        key = uuid.uuid4()
        ids = self.race(lambda _: self.register(key).pk)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ReciboEvento.objects.count(), 1)
        self.race(lambda _: confirm(ReciboEvento.objects.get(pk=ids[0]), self.owner, 'Verificado').pk)
        self.assertEqual(EntradaQR.objects.count(), 2)

    def test_last_coupon_slot_has_one_winner(self):
        coupon = CodigoDescuento.objects.create(evento=self.event, nombre_codigo='ULTIMO', limite_usos=1,
            fecha_caducidad=self.subscription.period_end, precio_especial=90)
        result = self.race(lambda _: self.register(uuid.uuid4(), coupon.nombre_codigo).pk)
        self.assertEqual(result.count('rejected'), 1)
        coupon.refresh_from_db()
        self.assertEqual(coupon.usos_actuales, 1)
        self.assertEqual(ReciboEvento.objects.count(), 1)

    def test_daily_checkin_consumes_one_access(self):
        receipt = self.register(uuid.uuid4())
        confirm(receipt, self.owner, 'Verificado')
        ticket = receipt.boletas_qr.first()
        result = self.race(lambda _: check_in(self.event, self.owner, ticket.codigo_unico).result)
        self.assertCountEqual(result, ['SUCCESS', 'ALREADY_USED_TODAY'])
        ticket.refresh_from_db()
        self.assertEqual(ticket.asistencias_consumidas, 1)
        self.assertEqual(CheckIn.objects.filter(result='SUCCESS').count(), 1)

    def test_invoice_and_bank_confirmation_create_once(self):
        ids = self.race(lambda _: invoice_subscription(self.tenant, self.now, self.subscription.period_end).pk)
        self.assertEqual(ids[0], ids[1])
        self.race(lambda _: settle(SaaSInvoice.objects.get(pk=ids[0]), reference='same-bank-transfer',
            amount=100, currency='COP', source='MANUAL').pk)
        self.assertEqual(SaaSInvoice.objects.count(), 1)
        self.assertEqual(SaaSPayment.objects.count(), 1)
