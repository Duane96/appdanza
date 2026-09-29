import re
import tempfile
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from apps.saas_core.models import DurableJob
from apps.planes_estudiantes.models import Estudiante, InscripcionPlan, Plan
from .models import Academia, PerfilUsuario, TenantMembership
from .invitations import invite_new_account, consume
from .forms import TenantLoginForm
from .student_identity import student_for
from gestoracademia.tenants import clear_current_tenant


class IdentityTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(nombre='Invitaciones', slug='invitaciones')
        self.user = User.objects.create_user(username='new', email='new@example.test', password=None,
                                             first_name='Mismo', last_name='Nombre')
        PerfilUsuario.objects.create(user=self.user, academia=self.tenant, rol='ESTUDIANTE')
        self.addCleanup(clear_current_tenant)

    def test_new_profile_adds_membership_and_invite_works_once(self):
        self.assertEqual(TenantMembership.objects.get(user=self.user).role, 'STUDENT')
        invitation = invite_new_account(self.user, self.tenant, base_url='https://appdanza.test')
        html = DurableJob.objects.get(kind='EMAIL').payload['html']
        token = re.search(r'/invitacion/([^/]+)/', html)[1]
        url = reverse('academias:accept_invitation', args=[self.tenant.slug, token])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'new_password1': 'Random-setup-93!safe', 'new_password2': 'Random-setup-93!safe'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Random-setup-93!safe'))
        with self.assertRaises(ValidationError):
            invite_new_account(self.user, self.tenant, base_url='https://appdanza.test')

    def test_ambiguous_legacy_identity_never_selects_first(self):
        fields = {'academia': self.tenant, 'nombres': 'Mismo', 'apellidos': 'Nombre', 'qr_code': 'fixtures/qr.png'}
        Estudiante.unfiltered_objects.create(**fields, identificacion='a')
        Estudiante.unfiltered_objects.create(**fields, identificacion='b')
        self.assertIsNone(student_for(self.user, self.tenant))
        own = Estudiante.unfiltered_objects.get(identificacion='b')
        own.user = self.user
        own.save()
        self.assertEqual(student_for(self.user, self.tenant), own)

    def test_email_login_is_tenant_scoped_and_invalid_login_does_not_disclose_identity(self):
        self.user.set_password('Secret-valid-123')
        self.user.save()
        request = RequestFactory().post('/invitaciones/login/')
        request.tenant = self.tenant
        foreign = Academia.objects.create(nombre='Foreign', slug='foreign')
        other = User.objects.create_user('other', email=self.user.email, password='Other-pass')
        PerfilUsuario.objects.create(user=other, academia=foreign, rol='ESTUDIANTE')
        form = TenantLoginForm(request, data={'username': self.user.email, 'password': 'Secret-valid-123'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), self.user)
        invalid = TenantLoginForm(request, data={'username': self.user.email, 'password': 'wrong'})
        self.assertFalse(invalid.is_valid())
        self.assertNotIn(self.user.first_name, str(invalid.errors))

    def test_cross_tenant_enrollment_is_rejected_at_model_boundary(self):
        other = Academia.objects.create(nombre='Otra', slug='otra')
        student = Estudiante.unfiltered_objects.create(academia=self.tenant, nombres='A', apellidos='B',
                                                       identificacion='a', qr_code='fixture/a.png')
        plan = Plan.unfiltered_objects.create(academia=other, nombre='Ajeno', precio=10)
        from django.utils import timezone
        with self.assertRaises(ValidationError):
            InscripcionPlan.unfiltered_objects.create(academia=self.tenant, estudiante=student, plan=plan,
                clases_restantes=8, fecha_fin=timezone.localdate())
