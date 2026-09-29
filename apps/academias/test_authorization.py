from decimal import Decimal
from django.contrib.auth.models import User, AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone
from apps.academias.authorization import can, authorize
from apps.academias.models import Academia, PerfilUsuario, TenantMembership
from apps.eventos.models import Evento, ReciboEvento, GastoEvento, TipoPase, ColaboradorEvento
from apps.eventos.forms import CodigoDescuentoForm
from apps.eventos.receipt_access import receipt_url
from apps.planes_estudiantes.models import Estudiante
from gestoracademia.tenants import set_current_tenant, get_current_tenant, clear_current_tenant
from gestoracademia.middleware import TenantMiddleware


class TenantAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Academia.objects.create(nombre='Academia A', slug='academia-a')
        cls.b = Academia.objects.create(nombre='Academia B', slug='academia-b')
        cls.users = {}
        for role in ('OWNER', 'ADMIN', 'TEACHER', 'STUDENT', 'BILLING'):
            user = User.objects.create(username=role.lower())
            TenantMembership.objects.create(user=user, academia=cls.a, role=role)
            cls.users[role] = user
        cls.outsider = User.objects.create(username='outsider')
        TenantMembership.objects.create(user=cls.outsider, academia=cls.b, role='OWNER')
        cls.superuser = User.objects.create(username='platform', is_superuser=True, is_staff=True)
        cls.staff = User.objects.create(username='staff-only', is_staff=True)
        cls.ea = Evento.unfiltered_objects.create(academia=cls.a, nombre='Evento A', fecha=timezone.now())
        cls.ea2 = Evento.unfiltered_objects.create(academia=cls.a, nombre='Otro evento A', fecha=timezone.now())
        cls.eb = Evento.unfiltered_objects.create(academia=cls.b, nombre='Evento B', fecha=timezone.now())
        cls.student = Estudiante.unfiltered_objects.create(academia=cls.a, nombres='Alumno', apellidos='A',
            identificacion='test-a', qr_code='test/alumno.png')
        cls.receipt = ReciboEvento.objects.create(evento=cls.ea, origen='PUERTA', comprador_nombre='Privado',
            revisado_por_admin=True, payment_status='LEGACY',
            monto_total=Decimal('100.00'), precio_unitario_aplicado=Decimal('100.00'))

    def tearDown(self):
        clear_current_tenant()

    def test_role_matrix_deny_by_default(self):
        for user in (AnonymousUser(), self.outsider, self.staff, self.users['TEACHER'], self.users['STUDENT']):
            with self.subTest(user=str(user)):
                self.assertFalse(can(user, self.a, 'tenant.admin'))
        for user in (self.users['OWNER'], self.users['ADMIN'], self.superuser):
            self.assertTrue(can(user, self.a, 'tenant.admin'))
        self.assertFalse(can(self.superuser, self.a, 'unknown.action'))
        self.assertFalse(can(self.users['OWNER'], self.a, 'events.manage', self.eb))

    def test_branding_heading_only_allows_formatting(self):
        from .templatetags.branding_text import safe_heading
        result = str(safe_heading('<span style="color:var(--gold-accent)" onclick="evil()">Baile</span><br><img src=x onerror=evil()><script>evil()</script>'))
        self.assertIn('color:var(--gold-accent)', result)
        self.assertIn('<br>', result)
        for forbidden in ('<script', '<img', 'onclick', 'onerror'):
            self.assertNotIn(forbidden, result)

    def test_inactive_membership_cannot_fall_back_to_profile(self):
        user = self.users['OWNER']
        PerfilUsuario.objects.create(user=user, academia=self.a, rol='ADMIN_ACADEMIA')
        TenantMembership.objects.filter(user=user).update(active=False)
        self.assertFalse(can(user, self.a, 'tenant.admin'))

    def test_multi_academy_membership_has_independent_roles(self):
        user = self.users['OWNER']
        TenantMembership.objects.create(user=user, academia=self.b, role='STUDENT')
        self.assertTrue(can(user, self.a, 'tenant.admin'))
        self.assertTrue(can(user, self.b, 'student.self'))
        self.assertFalse(can(user, self.b, 'tenant.admin'))

    def test_sensitive_apis_role_matrix(self):
        urls = [reverse('saas_core:api_finanzas_academia') + '?academia_id=' + str(self.a.pk),
                reverse('planes_estudiantes:api_estudiante', args=[self.a.slug, self.student.pk])]
        for user, status in [(None, 403), (self.outsider, 403), (self.staff, 403),
                             (self.users['TEACHER'], 403), (self.users['STUDENT'], 403),
                             (self.users['ADMIN'], 200), (self.superuser, 200)]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in urls:
                with self.subTest(user=str(user), url=url):
                    self.assertEqual(self.client.get(url).status_code, status)

    def test_foreign_tenant_get_post_detail_edit_delete_export_are_denied(self):
        self.client.force_login(self.outsider)
        urls = [reverse('eventos:admin_lista', args=[self.a.slug]),
                reverse('eventos:admin_detalle', args=[self.a.slug, self.ea.slug]),
                reverse('eventos:admin_editar', args=[self.a.slug, self.ea.slug]),
                reverse('planes_estudiantes:eliminar_plan', args=[self.a.slug, 999]),
                reverse('finanzas:exportar_reporte_contable', args=[self.a.slug]),
                reverse('eventos:anular_recibo', args=[self.a.slug, self.ea.slug, self.receipt.pk])]
        for url in urls:
            for method in ('get', 'post'):
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.receipt.refresh_from_db()
        self.assertFalse(self.receipt.anulado)

    def test_collaborator_is_scoped_to_assigned_event_and_action(self):
        ColaboradorEvento.objects.create(usuario=self.outsider, evento=self.ea, rol='TAQUILLA')
        self.assertTrue(can(self.outsider, self.a, 'events.checkin', self.ea))
        self.assertFalse(can(self.outsider, self.a, 'events.manage', self.ea))
        self.assertFalse(can(self.outsider, self.a, 'events.metrics', self.ea))
        self.assertFalse(can(self.outsider, self.a, 'events.checkin', self.ea2))
        self.assertFalse(can(self.outsider, self.a, 'tenant.admin'))
        ColaboradorEvento.objects.filter(usuario=self.outsider).update(rol='METRICAS')
        self.assertTrue(can(self.outsider, self.a, 'events.metrics', self.ea))
        self.assertFalse(can(self.outsider, self.a, 'events.sell', self.ea))

    def test_receipt_id_is_not_a_public_capability(self):
        url = reverse('eventos:registro_exito', args=[self.a.slug, self.receipt.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(receipt_url(self.receipt)).status_code, 200)
        self.assertEqual(self.client.get(url + '?token=forged').status_code, 403)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_coupon_form_never_accepts_another_events_pass(self):
        local = TipoPase.objects.create(evento=self.ea, nombre='Local', precio=100)
        foreign = TipoPase.objects.create(evento=self.eb, nombre='Ajeno', precio=100)
        self.assertEqual(list(CodigoDescuentoForm(evento=self.ea).fields['pase_aplicable'].queryset), [local])
        self.assertFalse(CodigoDescuentoForm().fields['pase_aplicable'].queryset.exists())
        form = CodigoDescuentoForm({'nombre_codigo': 'TEST', 'precio_especial': 50,
            'limite_usos': 10, 'pase_aplicable': foreign.pk}, evento=self.ea)
        self.assertFalse(form.is_valid())
        self.assertIn('pase_aplicable', form.errors)

    def test_no_context_is_not_global_and_cleanup_survives_exception(self):
        clear_current_tenant()
        self.assertFalse(Evento.objects.exists())
        set_current_tenant(self.a)
        self.assertEqual(Evento.objects.count(), 2)
        def failure(request):
            self.assertEqual(get_current_tenant(), self.a)
            raise RuntimeError('controlled test')
        with self.assertRaises(RuntimeError):
            TenantMiddleware(failure)(RequestFactory().get('/academia-a/'))
        self.assertIsNone(get_current_tenant())

    def test_event_state_get_cannot_mutate(self):
        self.client.force_login(self.users['OWNER'])
        url = reverse('eventos:cambiar_estado', args=[self.a.slug, self.ea.slug, 'FINALIZADO'])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.ea.refresh_from_db()
        self.assertNotEqual(self.ea.estado, 'FINALIZADO')

    def test_independent_financial_sums_keep_equal_legitimate_values(self):
        from apps.finanzas.reporting import event_totals
        ReciboEvento.objects.create(evento=self.ea, origen='PUERTA', comprador_nombre='B',
            revisado_por_admin=True, payment_status='LEGACY',
            monto_total=100, precio_unitario_aplicado=100)
        ReciboEvento.objects.create(evento=self.ea, origen='PUERTA', comprador_nombre='Anulado',
            monto_total=900, precio_unitario_aplicado=900, anulado=True)
        for _ in range(3):
            GastoEvento.objects.create(evento=self.ea, concepto='Gasto', monto=10)
        data = next(row for row in event_totals(self.a.pk) if row['nombre'] == self.ea.nombre)
        self.assertEqual(data['total_ingreso'], Decimal('200'))
        self.assertEqual(data['gastos'], Decimal('30'))
        self.assertEqual(data['neto'], Decimal('170'))
        self.assertEqual(data['cant_recibos'], 2)
