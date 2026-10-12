"""Regression tests for restoring access without altering existing credentials."""
from io import StringIO
from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.planes_estudiantes.models import Estudiante
from apps.saas_core.models import DurableJob
from .invitations import invite_new_account
from .models import Academia, AccountInvitation, PerfilUsuario


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StudentAccessRepairTests(TestCase):
    def setUp(self):
        self.tenant = Academia.objects.create(nombre="Luis y Camila", slug="luis-y-camila-test")
        self.other = Academia.objects.create(nombre="Otra academia", slug="otra-academia-test")

        self.missing = self.student("yeissonparra", tenant=self.tenant)
        self.existing = self.student(
            "edwinlozano", tenant=self.tenant, password="Existing-Strong-93!"
        )
        self.foreign = self.student("karengonzalez", tenant=self.other)
        self.teacher = User.objects.create_user(username="profesorprueba", password=None)
        PerfilUsuario.objects.create(
            user=self.teacher, academia=self.tenant, rol="PROFESOR"
        )

    def student(self, name, tenant, password=None):
        user = User.objects.create_user(
            username=name, email=f"{name}@example.test",
            first_name=name, last_name="Estudiante", password=password,
        )
        PerfilUsuario.objects.create(
            user=user, academia=tenant, rol="ESTUDIANTE"
        )
        Estudiante.unfiltered_objects.create(
            user=user, academia=tenant,
            nombres=name, apellidos="Estudiante",
            identificacion=f"id-{user.pk}", qr_code=f"fixtures/{name}.png",
        )
        return user

    def command(self, *names, apply=False, mode="manual"):
        out = StringIO()
        arguments = [
            "--academia", self.tenant.nombre,
            "--usuarios", *names, "--modo", mode,
        ]
        if apply:
            arguments.append("--apply")
        if mode == "invitacion":
            arguments.extend(["--base-url", "https://appdanza.example.test"])
        call_command("reparar_acceso_estudiantes", *arguments, stdout=out)
        return out.getvalue()

    def test_simulation_never_changes_accounts(self):
        text = self.command("yeissonparra", "edwinlozano", "karengonzalez", "profesorprueba")
        self.missing.refresh_from_db()
        self.existing.refresh_from_db()
        self.assertFalse(self.missing.has_usable_password())
        self.assertTrue(self.existing.check_password("Existing-Strong-93!"))
        self.assertFalse(self.foreign.has_usable_password())
        self.assertFalse(self.teacher.has_usable_password())
        self.assertIn("SIMULACIÓN", text)
        self.assertIn("contraseña existente: sin cambios", text)
        self.assertIn("sin membresía STUDENT activa", text)
        self.assertIn("apto para manual", text)

    @patch(
        "apps.academias.management.commands.reparar_acceso_estudiantes._prompt_password",
        return_value="New-Temporary-94!Safe",
    )
    def test_manual_change_only_updates_missing_qualified_student(self, prompt):
        invitation = invite_new_account(
            self.missing, self.tenant, base_url="https://appdanza.example.test"
        )
        with self.captureOnCommitCallbacks(execute=True):
            result = self.command(
                "yeissonparra", "edwinlozano", "karengonzalez", "profesorprueba",
                apply=True,
            )
        self.missing.refresh_from_db()
        self.existing.refresh_from_db()
        self.foreign.refresh_from_db()
        self.teacher.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(self.missing.check_password("New-Temporary-94!Safe"))
        self.assertTrue(self.existing.check_password("Existing-Strong-93!"))
        self.assertFalse(self.foreign.has_usable_password())
        self.assertFalse(self.teacher.has_usable_password())
        self.assertIsNotNone(invitation.consumed_at)
        self.assertEqual(
            DurableJob.objects.get(dedupe_key=f"invitation:{invitation.pk}").last_error,
            "SupersededByManualSetup",
        )
        self.assertEqual(prompt.call_count, 1)
        self.assertNotIn("New-Temporary-94!Safe", result)
        self.assertIn("'configurados': 1", result)
        with self.captureOnCommitCallbacks(execute=True):
            self.command("yeissonparra", apply=True)
        self.assertEqual(prompt.call_count, 1)

    def test_invitation_is_delivered_immediately_without_password_changes(self):
        with self.captureOnCommitCallbacks(execute=True):
            summary = self.command("yeissonparra", apply=True, mode="invitacion")
        self.missing.refresh_from_db()
        self.assertFalse(self.missing.has_usable_password())
        self.assertIn("'invitados': 1", summary)
        invitation = AccountInvitation.objects.get(user=self.missing)
        self.assertEqual(
            DurableJob.objects.get(dedupe_key=f"invitation:{invitation.pk}").state,
            "DONE",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.missing.email])
        self.assertIn("Crear mi contraseña", mail.outbox[0].alternatives[0][0])

    def test_wrong_academy_name_fails_without_changes(self):
        with self.assertRaises(CommandError):
            call_command(
                "reparar_acceso_estudiantes",
                "--academia", "academia-inexistente",
                "--usuarios", "yeissonparra", "--apply", stdout=StringIO(),
            )
        self.missing.refresh_from_db()
        self.assertFalse(self.missing.has_usable_password())

    def test_no_mail_mode_for_account_with_existing_password(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = self.command("edwinlozano", apply=True, mode="invitacion")
        self.assertIn("'invitados': 0", result)
        self.assertEqual(AccountInvitation.objects.filter(user=self.existing).count(), 0)

    def test_new_student_gets_immediate_setup_email_and_a_valid_link(self):
        from .models import TenantMembership
        admin = User.objects.create_user(
            username="organizador-acceso", password="Owner-Safe-53!"
        )
        TenantMembership.objects.create(
            user=admin, academia=self.tenant, role="OWNER",
        )
        self.client.force_login(admin)
        url = reverse("planes_estudiantes:crear_estudiante", args=[self.tenant.slug])
        with TemporaryDirectory() as private_media:
            with override_settings(PRIVATE_MEDIA_ROOT=private_media):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(url, {
                        "nombres": "Sofia",
                        "apellidos": "Ejemplo",
                        "identificacion": "test-student-2026",
                        "email": "sofia@example.test",
                        "telefono": "3000000000",
                    })
        self.assertEqual(response.status_code, 302)
        record = Estudiante.unfiltered_objects.get(
            academia=self.tenant, identificacion="test-student-2026",
        )
        self.assertIsNotNone(record.user_id)
        self.assertFalse(record.user.has_usable_password())
        invitation = AccountInvitation.objects.get(user=record.user)
        self.assertEqual(
            DurableJob.objects.get(dedupe_key=f"invitation:{invitation.pk}").state,
            "DONE",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sofia@example.test"])

    @patch(
        "apps.academias.management.commands.reparar_acceso_estudiantes.getpass",
        side_effect=["EntirelyNumericValue987", "EntirelyNumericValue987"],
    )
    @patch("apps.academias.management.commands.reparar_acceso_estudiantes.sys.stdin")
    def test_manual_password_is_validated_without_logging(self, stdin, prompt):
        from apps.academias.management.commands.reparar_acceso_estudiantes import _prompt_password
        stdin.isatty.return_value = True
        secret = _prompt_password(self.missing)
        self.assertEqual(secret, "EntirelyNumericValue987")
        self.assertEqual(prompt.call_count, 2)
