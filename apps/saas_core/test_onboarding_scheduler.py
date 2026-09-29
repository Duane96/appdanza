import hashlib
import secrets
from datetime import timedelta
from unittest.mock import Mock
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from apps.academias.models import Academia, TenantMembership
from .models import (PlanSaaS, PlanVersion, OnboardingRequest, BillingAccount, CommercialSubscription,
    PaymentMandate, PaymentAttempt, SaaSPayment, SaaSInvoice)
from .onboarding import provision
from .billing import invoice_subscription
from .billing_scheduler import schedule_attempt, charge_attempt
from .epayco import UnknownOutcome


class OnboardingTests(TestCase):
    def test_missing_catalog_has_controlled_public_state(self):
        response = self.client.get(reverse('saas_core:onboarding_signup'))
        self.assertContains(response, 'El registro de nuevas organizaciones se abrirá')
        self.assertNotContains(response, 'Verificar mi correo</button>')

    def test_verified_request_creates_workspace_owner_trial_once_and_no_debt(self):
        plan = PlanSaaS.objects.create(nombre='Piloto', precio_mensual=100)
        version = PlanVersion.objects.create(plan=plan, version=1, name='Piloto', amount=100,
            features={'eventos': True}, published=True)
        pending = OnboardingRequest.objects.create(token_hash=hashlib.sha256(b'test').hexdigest(),
            email='owner@example.test', academy_name='Organizador', requested_slug='organizador',
            workspace_type='EVENT_ORGANIZER', plan_version=version, expires_at=timezone.now()+timedelta(days=1))
        tenant = provision(pending)
        self.assertEqual(tenant.workspace_type, 'EVENT_ORGANIZER')
        self.assertEqual(tenant.billing_account.mode, 'TRIAL')
        self.assertFalse(tenant.billing_account.automatic_charges_authorized)
        self.assertEqual(TenantMembership.objects.get(academia=tenant).role, 'OWNER')
        self.assertFalse(User.objects.get(email=pending.email).has_usable_password())
        self.assertFalse(SaaSInvoice.objects.exists())
        with self.assertRaises(ValidationError):
            provision(pending)
        self.assertEqual(Academia.unfiltered_objects.count(), 1)


@override_settings(APPDANZA_AUTOMATIC_BILLING_ENABLED=True)
class BillingSchedulerTests(TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode()
        self.settings_override = override_settings(APPDANZA_TOKEN_ENCRYPTION_KEY=self.key)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.tenant = Academia.objects.create(nombre='Pago', slug='pago')
        self.account = BillingAccount.objects.create(academia=self.tenant, mode='PAID', automatic_charges_authorized=True)
        plan = PlanSaaS.objects.create(nombre='Piloto', precio_mensual=100)
        version = PlanVersion.objects.create(plan=plan, version=1, name='Piloto', amount=100)
        now = timezone.now()
        self.subscription = CommercialSubscription.objects.create(academia=self.tenant, plan_version=version,
            state='ACTIVE', period_start=now, period_end=now+timedelta(days=30), accepted_at=now)
        self.invoice = invoice_subscription(self.tenant, now, now+timedelta(days=30))
        self.mandate = PaymentMandate.objects.create(academia=self.tenant, customer_id='provider-customer',
            encrypted_token=Fernet(self.key.encode()).encrypt(b'opaque-test-token').decode(),
            document_type='CC', document_number='test', payer_name='Test', email='test@example.test', consent_ip='127.0.0.1')

    def test_timeout_is_unknown_and_never_retried_as_new_charge(self):
        attempt = schedule_attempt(self.invoice)
        provider = Mock()
        provider.charge.side_effect = UnknownOutcome('timeout')
        charge_attempt(attempt.pk, provider)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, 'UNKNOWN')
        self.assertEqual(schedule_attempt(self.invoice).pk, attempt.pk)
        charge_attempt(attempt.pk, provider)
        self.assertEqual(provider.charge.call_count, 1)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.assertFalse(SaaSPayment.objects.exists())

    def test_exemption_or_revoked_consent_blocks_pending_attempt(self):
        attempt = schedule_attempt(self.invoice)
        self.account.automatic_charges_authorized = False
        self.account.mode = 'COMPLIMENTARY'
        self.account.save()
        provider = Mock()
        charge_attempt(attempt.pk, provider)
        provider.charge.assert_not_called()

    def test_charge_success_still_waits_for_authoritative_confirmation(self):
        attempt = schedule_attempt(self.invoice)
        provider = Mock()
        provider.charge.return_value = {'success': True, 'data': {'ref_payco': 'ref1'}}
        charge_attempt(attempt.pk, provider)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, 'PENDING')
        self.assertFalse(SaaSPayment.objects.exists())

    def test_backend_refuses_raw_card_fields(self):
        user = User.objects.create_user('owner')
        TenantMembership.objects.create(academia=self.tenant, user=user, role='OWNER')
        self.client.force_login(user)
        response = self.client.post(reverse('saas_core:billing_mandate', args=[self.tenant.slug]),
                                    {'card[number]': 'test-pan', 'card[cvc]': 'test-cvv'})
        self.assertEqual(response.status_code, 400)
