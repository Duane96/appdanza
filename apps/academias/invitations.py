"""One-use setup for newly created accounts; never reset an existing password."""
import hashlib
import secrets
from datetime import timedelta
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods
from .models import AccountInvitation, TenantMembership
from apps.saas_core.audit import record
from apps.saas_core.jobs import enqueue


@transaction.atomic
def invite_new_account(user, tenant, *, base_url, actor=None):
    if user.has_usable_password():
        raise ValidationError('Este usuario ya tiene contraseña; utiliza la recuperación de acceso.')
    if not user.email:
        return None  # Staff can supply a verified delivery address before inviting.
    AccountInvitation.objects.filter(user=user, consumed_at=None).update(consumed_at=timezone.now())
    token = secrets.token_urlsafe(32)
    invitation = AccountInvitation.objects.create(user=user, academia=tenant,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now()+timedelta(days=3))
    url = base_url.rstrip('/') + reverse('academias:accept_invitation', args=[tenant.slug, token])
    enqueue('EMAIL', {'subject': 'Configura tu acceso a AppDanza', 'to': [user.email],
        'html': str(format_html('<p>Te invitamos a {}.</p><p><a href="{}">Crear mi contraseña</a></p>'
                               '<p>Este enlace vence en tres días y sólo se puede usar una vez.</p>', tenant.nombre, url))},
        tenant=tenant, key=f'invitation:{invitation.pk}')
    record(tenant, actor, 'identity.invitation.created', invitation.pk)
    return invitation


@transaction.atomic
def consume(invitation, form):
    now = timezone.now()
    # Conditional write is both the one-use guard and SQLite serialization point.
    updated = AccountInvitation.objects.filter(pk=invitation.pk, consumed_at=None,
        expires_at__gt=now).update(consumed_at=now)
    if not updated:
        raise ValidationError('El enlace venció o ya fue utilizado.')
    invitation.user.refresh_from_db()
    if invitation.user.has_usable_password():
        raise ValidationError('La cuenta ya fue configurada.')
    form.user = invitation.user
    form.save()
    record(invitation.academia, invitation.user, 'identity.invitation.accepted', invitation.pk)


@require_http_methods(['GET', 'POST'])
def accept(request, slug_academia, token):
    invitation = AccountInvitation.objects.select_related('user', 'academia').filter(
        academia=request.tenant, token_hash=hashlib.sha256(token.encode()).hexdigest(),
        consumed_at=None, expires_at__gt=timezone.now()).first()
    if invitation is None:
        return render(request, 'academias/invitation.html', {'expired': True}, status=400)
    form = SetPasswordForm(invitation.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            consume(invitation, form)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect('academias:login', slug_academia=slug_academia)
    response = render(request, 'academias/invitation.html', {'form': form, 'academia': request.tenant})
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
