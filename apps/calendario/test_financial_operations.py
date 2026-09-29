import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.academias.models import Academia, TenantMembership
from apps.planes_estudiantes.models import Estudiante, Plan, InscripcionPlan
from apps.profesores.models import Profesor, OrdenPagoMensual
from apps.profesores.operations import prepare, decide, pay
from apps.asistencias.operations import mark
from apps.asistencias.models import Asistencia
from apps.finanzas.models import ReciboIngreso, Gasto
from apps.finanzas.operations import annul
from apps.tienda.models import Producto, VentaTienda
from gestoracademia.tenants import set_current_tenant, clear_current_tenant
from .models import Clase, SesionClase, ReservaEstudiante
from .reservations import change_reservation


class AcademyFinancialOperationsTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(nombre='Operaciones', slug='operaciones')
        self.owner = User.objects.create_user('owner')
        self.student_user = User.objects.create_user('student')
        self.teacher_user = User.objects.create_user('teacher')
        for user, role in ((self.owner, 'OWNER'), (self.student_user, 'STUDENT'), (self.teacher_user, 'TEACHER')):
            TenantMembership.objects.create(user=user, academia=self.tenant, role=role)
        self.student = Estudiante.unfiltered_objects.create(academia=self.tenant, user=self.student_user,
            nombres='Alumno', apellidos='Test', identificacion='test', qr_code='fixture/qr.png', estado='ACTIVO')
        plan = Plan.unfiltered_objects.create(academia=self.tenant, nombre='8 clases', precio=100)
        self.enrollment = InscripcionPlan.unfiltered_objects.create(academia=self.tenant, estudiante=self.student,
            plan=plan, clases_restantes=8, fecha_fin=timezone.localdate()+timedelta(days=30))
        self.teacher = Profesor.unfiltered_objects.create(academia=self.tenant, usuario=self.teacher_user,
            documento_identidad='test', telefono='test', tarifa_base=50, tipo_pago='MENSUAL')
        self.class_ = Clase.unfiltered_objects.create(academia=self.tenant, nombre='Clase', limite_cupos=1)
        self.session = SesionClase.unfiltered_objects.create(academia=self.tenant, clase=self.class_,
            profesor_asignado=self.teacher, fecha_hora_inicio=timezone.now()+timedelta(hours=2),
            fecha_hora_fin=timezone.now()+timedelta(hours=3))
        set_current_tenant(self.tenant)
        self.addCleanup(clear_current_tenant)

    def test_reserve_retry_and_cancellation_refund_original_plan_once(self):
        for _ in range(2):
            change_reservation(self.tenant, self.student_user, self.session.pk, 'RESERVAR')
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.clases_restantes, 7)
        for _ in range(2):
            change_reservation(self.tenant, self.student_user, self.session.pk, 'CANCELAR')
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.clases_restantes, 8)
        self.assertEqual(ReservaEstudiante.unfiltered_objects.count(), 1)
        self.assertFalse(ReservaEstudiante.unfiltered_objects.get().active)

    def test_attendance_does_not_charge_reserved_class_again(self):
        change_reservation(self.tenant, self.student_user, self.session.pk, 'RESERVAR')
        during = self.session.fecha_hora_inicio+timedelta(minutes=1)
        with patch('django.utils.timezone.now', return_value=during):
            for _ in range(2):
                mark(self.tenant, self.owner, token=self.student.token_asistencia)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.clases_restantes, 7)
        self.assertEqual(Asistencia.unfiltered_objects.count(), 1)

    def test_per_class_payment_and_monthly_recording_are_idempotent(self):
        from apps.profesores.operations import mark_session
        self.teacher.tipo_pago = 'POR_CLASE'
        self.teacher.save()
        for _ in range(2):
            mark_session(self.tenant, self.owner, self.session.pk, True)
        self.session.refresh_from_db()
        self.assertTrue(self.session.pagada_al_profesor)
        self.assertEqual(Gasto.objects.count(), 1)
        self.assertEqual(Gasto.objects.get().monto, 50)

    def test_paid_session_cannot_be_reopened_from_exception_form(self):
        from apps.profesores.operations import mark_session
        mark_session(self.tenant, self.owner, self.session.pk)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('calendario:excepcion_sesion', args=[self.tenant.slug, self.session.pk]),
            {'estado': 'PROGRAMADA', 'notas_excepcion': 'Reintento'})
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.estado, 'DICTADA')

    def test_annul_preserves_enrollment_and_link(self):
        receipt = ReciboIngreso.objects.create(academia=self.tenant, inscripcion=self.enrollment, monto=100,
            concepto='Plan', cliente_nit='test', cliente_nombre='test')
        for _ in range(2):
            annul(self.tenant, self.owner, 'ingreso', receipt.pk, 'Error de registro')
        self.enrollment.refresh_from_db()
        receipt.refresh_from_db()
        self.assertIsNotNone(self.enrollment.cancelled_at)
        self.assertEqual(receipt.inscripcion_id, self.enrollment.pk)
        self.assertEqual(self.enrollment.clases_restantes, 8)
        with self.assertRaises(ValidationError):
            change_reservation(self.tenant, self.student_user, self.session.pk, 'RESERVAR')

    def test_payroll_prepare_approve_and_pay_retry_emit_one_expense(self):
        self.session.estado = 'DICTADA'
        self.session.save()
        order = prepare(self.tenant, self.teacher_user)
        self.assertEqual(prepare(self.tenant, self.teacher_user).pk, order.pk)
        decide(self.tenant, self.teacher_user, order.pk, 'APROBAR')
        for _ in range(2):
            pay(self.tenant, self.owner, order.pk)
        self.assertEqual(Gasto.objects.count(), 1)
        self.assertEqual(OrdenPagoMensual.unfiltered_objects.count(), 1)
        with self.assertRaises(ValidationError):
            decide(self.tenant, self.teacher_user, order.pk, 'REVISAR')

    def test_pos_retry_and_double_annul_preserve_stock_and_one_receipt(self):
        product = Producto.objects.create(academia=self.tenant, nombre='Agua', stock=1,
            precio_compra_actual=10, precio_venta_actual=20)
        self.client.force_login(self.owner)
        data = {'request_key': str(uuid.uuid4()), 'carrito': [{'id': product.pk, 'cantidad': 1}], 'medio_pago': 'EFECTIVO'}
        # URL contract used by the POS template.
        for _ in range(2):
            response = self.client.post('/operaciones/tienda/pos/pagar/', data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
        product.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(VentaTienda.objects.count(), 1)
        receipt = ReciboIngreso.objects.get()
        for _ in range(2):
            annul(self.tenant, self.owner, 'ingreso', receipt.pk, 'Venta anulada')
        product.refresh_from_db()
        self.assertEqual(product.stock, 1)
