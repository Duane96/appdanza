"""Restore access only for uniquely linked student users without usable passwords.

Default operation is read-only. Passwords entered interactively are never
printed, logged, exposed in CLI arguments, or stored in plaintext.
"""
import sys
from getpass import getpass
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.academias.models import Academia, AccountInvitation, PerfilUsuario, TenantMembership
from apps.planes_estudiantes.models import Estudiante
from apps.saas_core.audit import record


def _eligible(user, tenant):
    if user is None:
        return "cuenta inexistente"
    if not user.is_active or user.is_staff or user.is_superuser:
        return "cuenta no apta para recuperación de estudiante"
    if user.has_usable_password():
        return "contraseña existente: sin cambios"
    membership = TenantMembership.objects.filter(user=user, academia=tenant).first()
    if not membership or not membership.active or membership.role != "STUDENT":
        return "sin membresía STUDENT activa en esta academia"
    if TenantMembership.objects.filter(user=user).exclude(academia=tenant).exists():
        return "cuenta compartida con otra academia: requiere revisión"
    if not PerfilUsuario.objects.filter(
        user=user, academia=tenant, rol="ESTUDIANTE"
    ).exists():
        return "perfil de estudiante no coincide"
    if Estudiante.unfiltered_objects.filter(user=user, academia=tenant).count() != 1:
        return "ficha de estudiante ausente o ambigua"
    if Estudiante.unfiltered_objects.filter(user=user).exclude(academia=tenant).exists():
        return "ficha vinculada a otra academia: requiere revisión"
    return None


def _prompt_password(user):
    if not sys.stdin.isatty():
        raise CommandError(
            "La opción manual requiere una consola interactiva para ocultar la contraseña."
        )
    candidate = getpass(f"Nueva contraseña temporal para {user.username}: ")
    repeat = getpass("Repítela para confirmar: ")
    if not candidate or candidate != repeat:
        raise CommandError("Las contraseñas no coinciden o están vacías. No se modificó la cuenta.")
    try:
        validate_password(candidate, user=user)
    except ValidationError as exc:
        raise CommandError("La nueva contraseña no cumple la política de seguridad.") from exc
    return candidate


def _resolve_tenant(value):
    matches = list(Academia.objects.filter(
        Q(slug__iexact=value) | Q(nombre__iexact=value)
    ).distinct()[:2])
    if len(matches) != 1:
        raise CommandError("Indica el nombre o slug exacto de una única academia.")
    return matches[0]


class Command(BaseCommand):
    help = "Diagnostica y habilita el acceso de estudiantes sin contraseña; nunca sobrescribe una existente."

    def add_arguments(self, parser):
        parser.add_argument("--academia", required=True, help="Nombre o slug exacto de la academia")
        parser.add_argument("--usuarios", nargs="+", required=True, help="Usuarios a revisar")
        parser.add_argument("--apply", action="store_true", help="Aplicar exclusivamente las cuentas aptas")
        parser.add_argument(
            "--modo", choices=("manual", "invitacion", "documento"), default="manual",
            help="manual: clave interactiva; invitacion: enlace por correo; documento: contraseña temporal basada en la identificación registrada",
        )
        parser.add_argument(
            "--base-url", default="", help="URL pública HTTPS obligatoria en modo invitacion"
        )

    def handle(self, *args, **opts):
        tenant = _resolve_tenant(opts["academia"])
        mode = opts["modo"]
        apply = opts["apply"]
        if apply and mode == "invitacion":
            url = urlsplit(opts["base_url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise CommandError("Usa --base-url con la URL HTTPS pública de AppDanza.")
        User = get_user_model()
        unique = list(dict.fromkeys(name.strip() for name in opts["usuarios"] if name.strip()))
        if not unique:
            raise CommandError("No se proporcionaron usuarios.")
        summary = {"revisados": 0, "aptos": 0, "configurados": 0, "invitados": 0, "omitidos": 0}
        for name in unique:
            summary["revisados"] += 1
            accounts = list(User.objects.filter(username__iexact=name)[:2])
            if len(accounts) > 1:
                self.stdout.write(f"{name}: usuario ambiguo, omitido.")
                summary["omitidos"] += 1
                continue
            user = accounts[0] if accounts else None
            reason = _eligible(user, tenant)
            if reason:
                self.stdout.write(f"{name}: {reason}.")
                summary["omitidos"] += 1
                continue
            if mode == "invitacion" and not user.email:
                self.stdout.write(f"{name}: sin correo, omitido.")
                summary["omitidos"] += 1
                continue
            summary["aptos"] += 1
            if not apply:
                self.stdout.write(f"{name}: apto para {mode}; no se modificó.")
                continue
            password = _prompt_password(user) if mode == "manual" else None
            try:
                with transaction.atomic():
                    locked = User.objects.select_for_update().get(pk=user.pk)
                    reason = _eligible(locked, tenant)
                    if reason:
                        self.stdout.write(f"{name}: {reason}.")
                        summary["omitidos"] += 1
                        continue
                    if mode == "documento":
                        student = Estudiante.unfiltered_objects.get(user=locked, academia=tenant)
                        candidate = (student.identificacion or "").strip()
                        if not candidate or len(candidate) < 5:
                            raise CommandError("Documento ausente o demasiado corto; cuenta sin cambios.")
                        locked.set_password(candidate)
                        locked.save(update_fields=["password"])
                        AccountInvitation.objects.filter(
                            user=locked, consumed_at__isnull=True
                        ).update(consumed_at=timezone.now())
                        record(
                            tenant, None, "identity.student_password.initialized", locked.pk,
                            reason="Recuperación de credencial inicial por documento",
                        )
                        summary["configurados"] += 1
                    elif mode == "manual":
                        locked.set_password(password)
                        locked.save(update_fields=["password"])
                        active_invitations = list(
                            AccountInvitation.objects.filter(
                                user=locked, consumed_at__isnull=True
                            ).values_list("pk", flat=True)
                        )
                        AccountInvitation.objects.filter(
                            pk__in=active_invitations
                        ).update(consumed_at=timezone.now())
                        # Prevent queued setup links from being sent after manual setup.
                        from apps.saas_core.models import DurableJob
                        DurableJob.objects.filter(
                            dedupe_key__in=[f"invitation:{pk}" for pk in active_invitations],
                            state="PENDING",
                        ).update(
                            state="FAILED", attempts=5,
                            last_error="SupersededByManualSetup", payload={},
                        )
                        record(
                            tenant, None, "identity.student_password.initialized", locked.pk,
                            reason="Configuración de acceso solicitada por administrador",
                        )
                        summary["configurados"] += 1
                    else:
                        from apps.academias.invitations import invite_new_account
                        invite_new_account(
                            locked, tenant, base_url=opts["base_url"],
                        )
                        summary["invitados"] += 1
                self.stdout.write(f"{name}: acceso actualizado mediante {mode}.")
            finally:
                # Do not retain credentials longer than required for this iteration.
                password = None
        state = "APLICADO" if apply else "SIMULACIÓN (sin cambios)"
        self.stdout.write(self.style.SUCCESS(f"{state}: {summary}"))
