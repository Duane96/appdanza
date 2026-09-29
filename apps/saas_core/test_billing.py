import uuid
from decimal import Decimal
from datetime import timedelta
from unittest.mock import Mock
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.academias.models import Academia, TenantMembership
from apps.eventos.models import Evento, TipoPase, ReciboEvento, EntradaQR
from apps.eventos.operations import register, confirm, reissue, check_in
from .models import (BillingAccount, PlanSaaS, PlanVersion, CommercialSubscription, EventFeeRate,
    UsageEntry, SaaSInvoice, SaaSPayment, PaymentAttempt, ProviderEvent, ProviderEventResult, DurableJob)
from .policy import BillingPolicy, EntitlementService
from .billing import invoice_subscription, close_usage, settle, update_dunning
from .epayco import receive_webhook, signature, config, process_provider_event


@override_settings(APPDANZA_EPAYCO_PUBLIC_KEY='test-public', APPDANZA_EPAYCO_PRIVATE_KEY='test-private',
    APPDANZA_EPAYCO_CUSTOMER_ID='test-merchant', APPDANZA_EPAYCO_P_KEY='test-signing', APPDANZA_EPAYCO_TEST=True)
class BillingTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(nombre='Externa', slug='externa')
        self.owner = User.objects.create_user('owner')
        TenantMembership.objects.create(user=self.owner, academia=self.tenant, role='OWNER')
        self.account = BillingAccount.objects.create(academia=self.tenant, mode='PAID')
        plan = PlanSaaS.objects.create(nombre='Piloto', precio_mensual=100)
        self.version = PlanVersion.objects.create(plan=plan, version=1, name='Piloto v1', amount=100,
            features={'eventos': True, 'estudiantes': True, 'max_students': 2}, published=True)
        self.now = timezone.now()
        self.subscription = CommercialSubscription.objects.create(academia=self.tenant, plan_version=self.version,
            state='ACTIVE', period_start=self.now, period_end=self.now+timedelta(days=30), accepted_at=self.now-timedelta(seconds=1))
        self.event = Evento.unfiltered_objects.create(academia=self.tenant, nombre='Evento', fecha=self.now+timedelta(days=1))
        self.pass_ = TipoPase.objects.create(evento=self.event, nombre='Pareja', precio=100, admissions_per_unit=2, qrs_por_pase=2)

    def invoice(self):
        return invoice_subscription(self.tenant, self.now, self.now+timedelta(days=30))

    def test_portal_payment_history_is_tenant_scoped_and_master_has_real_counts(self):
        payment = settle(self.invoice(), reference='bank-visible', amount=100, currency='COP', source='MANUAL')
        other = Academia.objects.create(nombre='Otra', slug='otra')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('saas_core:billing_portal', args=[self.tenant.slug]))
        self.assertContains(response, 'bank-visible')
        self.assertEqual(list(response.context['payments']), [payment])
        self.assertEqual(self.client.get(reverse('saas_core:billing_portal', args=[other.slug])).status_code, 403)
        self.owner.is_superuser = True
        self.owner.is_staff = True
        self.owner.save()
        response = self.client.get('/master/billing/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tenant_total'], 2)
        self.assertEqual(response.context['accounts'][0].event_count, 1)

    def sale(self):
        receipt = register(self.event, {'comprador_nombre': 'Test', 'comprador_telefono': 'test', 'cantidad_entradas': 1},
            key=uuid.uuid4(), pass_input='PASE_'+str(self.pass_.pk))
        confirm(receipt, self.owner, 'Verificado')
        return receipt

    def test_internal_and_complimentary_never_create_subscription_debt_or_dunning(self):
        for mode in ('COMPLIMENTARY', 'INTERNAL'):
            self.account.mode = mode
            self.account.grant_features = self.version.features
            self.account.save()
            self.assertTrue(BillingPolicy(self.tenant).exempt)
            self.assertIsNone(self.invoice())
            self.assertEqual(update_dunning(self.tenant), 'EXEMPT')
        self.account.mode = 'PAID'
        with self.assertRaises(ValidationError):
            self.account.save()
        self.assertEqual(SaaSInvoice.objects.count(), 0)

    def test_plan_versions_are_immutable_and_existing_contract_keeps_snapshot(self):
        self.version.amount = 999
        with self.assertRaises(ValidationError):
            self.version.save()
        self.version.plan.precio_mensual = 888
        self.version.plan.save()
        self.assertEqual(self.invoice().amount, Decimal('100'))

    def test_invoice_and_payment_are_idempotent(self):
        invoice = self.invoice()
        self.assertEqual(self.invoice().pk, invoice.pk)
        payment = settle(invoice, reference='manual-bank-1', amount=100, currency='COP', source='MANUAL', actor=self.owner)
        self.assertEqual(settle(invoice, reference='manual-bank-1', amount=100, currency='COP', source='MANUAL').pk, payment.pk)
        self.assertEqual(SaaSPayment.objects.count(), 1)
        with self.assertRaises(ValidationError):
            settle(invoice, reference='manual-bank-2', amount=100, currency='COP', source='MANUAL')

    def test_dunning_grace_limit_suspend_and_payment_recovers_without_deletion(self):
        invoice = self.invoice()
        self.assertEqual(update_dunning(self.tenant, self.now+timedelta(days=1)), 'PAST_DUE')
        self.assertEqual(update_dunning(self.tenant, self.now+timedelta(days=8)), 'LIMITED')
        self.assertEqual(update_dunning(self.tenant, self.now+timedelta(days=22)), 'SUSPENDED')
        settle(invoice, reference='late-bank', amount=100, currency='COP', source='MANUAL')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.state, 'ACTIVE')
        self.assertTrue(Evento.unfiltered_objects.filter(pk=self.event.pk).exists())

    def test_usage_requires_confirmation_and_explicit_units_not_qr_or_scans(self):
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=3, percentage=2, reason='Tarifa de prueba')
        receipt = self.sale()
        self.assertEqual(UsageEntry.objects.count(), 2)
        self.assertEqual(sum(u.amount for u in UsageEntry.objects.all()), Decimal('8'))
        confirm(receipt, self.owner, 'Reintento')
        ticket = receipt.boletas_qr.first()
        reissue(ticket, self.owner, 'Reemisión autorizada')
        check_in(self.event, self.owner, ticket.codigo_unico)
        self.assertEqual(UsageEntry.objects.count(), 2)
        self.assertEqual(EntradaQR.objects.count(), 2)

    def test_rate_override_exemption_and_zero_price(self):
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=9, reason='Global')
        EventFeeRate.objects.create(scope='TENANT', academia=self.tenant, fixed_per_admission=5, reason='Academia')
        EventFeeRate.objects.create(scope='EVENT', evento=self.event, fixed_per_admission=2, reason='Evento')
        self.sale()
        self.assertEqual(set(UsageEntry.objects.values_list('amount', flat=True)), {Decimal('2')})
        self.account.mode = 'COMPLIMENTARY'
        self.account.save()
        receipt = self.sale()
        self.assertEqual(set(UsageEntry.objects.filter(admission__receipt=receipt).values_list('reason', flat=True)), {'BILLING_EXEMPT'})

    def test_legacy_multiplier_is_not_a_commercial_unit(self):
        self.pass_.admissions_per_unit = None
        self.pass_.save()
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=20, reason='Prueba')
        self.sale()
        self.assertFalse(UsageEntry.objects.filter(billable=True).exists())
        self.assertEqual(EntradaQR.objects.count(), 2)

    def test_usage_close_is_idempotent(self):
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=2, reason='Prueba')
        self.sale()
        end = timezone.now()
        invoice = close_usage(self.tenant, self.now, end)
        self.assertEqual(invoice.amount, Decimal('4'))
        self.assertEqual(close_usage(self.tenant, self.now, end).pk, invoice.pk)
        self.assertEqual(invoice.lines.count(), 2)

    def test_full_event_refund_credits_only_new_usage_and_preserves_invoice_face(self):
        from apps.eventos.operations import record_refund
        from .models import SaaSCredit
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=2, reason='Prueba')
        receipt = self.sale()
        invoice = close_usage(self.tenant, self.now, timezone.now())
        record_refund(receipt, self.owner, amount=100, reference='returned-bank', reason='Devolución verificada')
        record_refund(receipt, self.owner, amount=100, reference='returned-bank', reason='Reintento')
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount, Decimal('4'))
        self.assertEqual(invoice.payable_amount, Decimal('0'))
        self.assertEqual(invoice.state, 'VOID')
        self.assertEqual(SaaSCredit.objects.count(), 2)
        self.assertEqual(UsageEntry.objects.count(), 2)
        self.assertFalse(SaaSPayment.objects.exists())

    def test_cancellation_is_not_a_usage_refund(self):
        from apps.eventos.operations import cancel
        from .models import SaaSCredit
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=2, reason='Prueba')
        receipt = self.sale()
        cancel(receipt, self.owner, 'Acceso cancelado sin devolución bancaria')
        self.assertFalse(SaaSCredit.objects.exists())
        self.assertEqual(close_usage(self.tenant, self.now, timezone.now()).amount, Decimal('4'))

    def test_refund_before_usage_close_does_not_become_an_invoice(self):
        from apps.eventos.operations import record_refund
        EventFeeRate.objects.create(scope='GLOBAL', fixed_per_admission=2, reason='Prueba')
        receipt = self.sale()
        record_refund(receipt, self.owner, amount=100, reference='before-close', reason='Devolución verificada')
        self.assertIsNone(close_usage(self.tenant, self.now, timezone.now()))

    def test_unknown_payment_reconciles_without_another_charge(self):
        from .epayco import reconcile_reference
        invoice = self.invoice()
        attempt = PaymentAttempt.objects.create(invoice=invoice, state='UNKNOWN')
        provider = Mock()
        provider.lookup.return_value = self.data(invoice)
        self.assertEqual(reconcile_reference('123456', provider).state, 'PROCESSED')
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, 'SUCCEEDED')
        self.assertEqual(SaaSPayment.objects.count(), 1)
        provider.charge.assert_not_called()

    def data(self, invoice, **extra):
        data = {'x_cust_id_cliente': 'test-merchant', 'x_ref_payco': '123456', 'x_transaction_id': 'txn1',
            'x_id_invoice': invoice.reference, 'x_amount': '100.00', 'x_currency_code': 'COP',
            'x_cod_transaction_state': '1', 'x_test_request': 'true'}
        data.update(extra)
        data['x_signature'] = signature(data, config())
        return data

    def test_webhook_duplicate_is_idempotent_and_signed_state_is_verified_separately(self):
        invoice = self.invoice()
        data = self.data(invoice)
        event = receive_webhook(data)
        self.assertEqual(receive_webhook(data).pk, event.pk)
        provider = Mock()
        provider.lookup.return_value = {**data, 'x_cod_transaction_state': '2'}
        process_provider_event(event.pk, provider)
        self.assertFalse(SaaSPayment.objects.exists())
        changed = receive_webhook(self.data(invoice, x_cod_transaction_state='3'))
        provider.lookup.return_value = data
        process_provider_event(changed.pk, provider)
        process_provider_event(changed.pk, provider)
        self.assertEqual(SaaSPayment.objects.count(), 1)
        later = receive_webhook(self.data(invoice, x_cod_transaction_state='4'))
        provider.lookup.return_value = {**data, 'x_cod_transaction_state': '4'}
        process_provider_event(later.pk, provider)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, 'PAID')

    def test_webhook_rejects_wrong_merchant_signature_mode_and_amount(self):
        invoice = self.invoice()
        for extra in ({'x_cust_id_cliente': 'foreign'}, {'x_test_request': 'false'}):
            with self.assertRaises(ValidationError):
                receive_webhook(self.data(invoice, **extra))
        data = self.data(invoice)
        data['x_signature'] = 'forged'
        with self.assertRaises(ValidationError):
            receive_webhook(data)
        event = receive_webhook(self.data(invoice))
        provider = Mock()
        provider.lookup.return_value = self.data(invoice, x_amount='1.00')
        process_provider_event(event.pk, provider)
        self.assertEqual(ProviderEventResult.objects.get(event=event).state, 'REVIEW')
        self.assertFalse(SaaSPayment.objects.exists())

    def test_billing_portal_only_owner_billing_or_platform(self):
        for role, expected in [('OWNER', 200), ('ADMIN', 403), ('TEACHER', 403), ('STUDENT', 403), ('BILLING', 200)]:
            TenantMembership.objects.filter(user=self.owner).update(role=role)
            self.client.force_login(self.owner)
            response = self.client.get(reverse('saas_core:billing_portal', args=[self.tenant.slug]))
            self.assertEqual(response.status_code, expected, role)
