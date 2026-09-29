import hashlib
import secrets
import uuid
from datetime import timedelta
from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods
from apps.academias.models import Academia, PerfilUsuario
from apps.academias.invitations import invite_new_account
from .models import OnboardingRequest, PlanVersion, BillingAccount, SuscripcionAcademia
from .jobs import enqueue
from .audit import record


class OnboardingForm(forms.Form):
    academy_name = forms.CharField(label='Nombre de tu academia u organización', max_length=150)
    requested_slug = forms.SlugField(label='Identificador público (letras, números y guiones)', max_length=100)
    email = forms.EmailField(label='Correo del propietario')
    workspace_type = forms.ChoiceField(label='Tipo de organización', choices=[('ACADEMY', 'Academia'), ('EVENT_ORGANIZER', 'Organizador de eventos')])
    plan_version = forms.ModelChoiceField(label='Plan de referencia para el piloto', queryset=PlanVersion.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plan_version'].queryset = PlanVersion.objects.filter(published=True)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_requested_slug(self):
        slug = self.cleaned_data['requested_slug'].lower()
        if slug in {'admin', 'master', 'api', 'billing', 'static', 'media', 'private-media', 'registro', 'verificar'}:
            raise ValidationError('Ese identificador está reservado.')
        if Academia.unfiltered_objects.filter(slug=slug).exists():
            raise ValidationError('Ese identificador ya está en uso.')
        return slug


@require_http_methods(['GET', 'POST'])
def signup(request):
    form = OnboardingForm(request.POST or None)
    sent = False
    if request.method == 'POST' and form.is_valid():
        values = form.cleaned_data
        # Bound repeated email submissions; do not disclose whether a User exists.
        recent = OnboardingRequest.objects.filter(email__iexact=values['email'], created_at__gte=timezone.now()-timedelta(minutes=10)).exists()
        if not recent and not User.objects.filter(email__iexact=values['email']).exists():
            token = secrets.token_urlsafe(32)
            with transaction.atomic():
                pending = OnboardingRequest.objects.create(**values, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=timezone.now()+timedelta(days=1))
                url = settings.APPDANZA_PUBLIC_URL.rstrip('/')+reverse('saas_core:onboarding_verify', args=[token])
                enqueue('EMAIL', {'subject': 'Verifica tu correo para crear tu organización en AppDanza', 'to': [values['email']],
                    'html': str(format_html('<p>Confirma tu correo para crear {}.</p><p><a href="{}">Continuar</a></p><p>El enlace vence en 24 horas.</p>', values['academy_name'], url))},
                    key=f'onboarding:{pending.pk}')
        sent = True
    return render(request, 'saas_core/onboarding.html', {'form': form, 'sent': sent,
        'catalog_available': form.fields['plan_version'].queryset.exists()})


@transaction.atomic
def provision(pending):
    now = timezone.now()
    if not OnboardingRequest.objects.filter(pk=pending.pk, consumed_at=None, expires_at__gt=now).update(consumed_at=now):
        raise ValidationError('La invitación venció o ya fue utilizada.')
    if User.objects.filter(email__iexact=pending.email).exists() or Academia.unfiltered_objects.filter(slug=pending.requested_slug).exists():
        raise ValidationError('El correo o identificador ya se encuentra registrado. Inicia sesión o contacta con soporte.')
    version = pending.plan_version
    if not version.published:
        raise ValidationError('El plan ya no está disponible para nuevas organizaciones.')
    days = int(getattr(settings, 'APPDANZA_PILOT_TRIAL_DAYS', 14))
    tenant = Academia.unfiltered_objects.create(nombre=pending.academy_name, slug=pending.requested_slug,
        workspace_type=pending.workspace_type, es_solo_eventos=pending.workspace_type == 'EVENT_ORGANIZER')
    user = User.objects.create_user(username='owner-'+uuid.uuid4().hex[:16], email=pending.email, password=None)
    PerfilUsuario.objects.create(user=user, academia=tenant, rol='ADMIN_ACADEMIA')
    SuscripcionAcademia.objects.create(academia=tenant, plan=version.plan, estado='PRUEBA',
        fecha_inicio=now.date(), fecha_vencimiento=(now+timedelta(days=days)).date(), ya_uso_prueba_gratis=True,
        dias_regalados_prueba=days)
    BillingAccount.objects.create(academia=tenant, mode='TRIAL', grant_until=now+timedelta(days=days),
        grant_features=version.features, billing_email=pending.email,
        grant_reason='Prueba configurada del piloto. No se convierte automáticamente en un contrato pago.')
    invite_new_account(user, tenant, base_url=settings.APPDANZA_PUBLIC_URL)
    record(tenant, None, 'tenant.onboarding.verified', tenant.pk, service='onboarding')
    return tenant


@require_http_methods(['GET', 'POST'])
def verify(request, token):
    pending = OnboardingRequest.objects.select_related('plan_version__plan').filter(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), consumed_at=None, expires_at__gt=timezone.now()).first()
    error = ''
    completed = False
    if pending is None:
        error = 'El enlace venció o ya fue utilizado.'
    elif request.method == 'POST':
        try:
            provision(pending)
            completed = True
        except ValidationError as exc:
            error = '; '.join(exc.messages)
    response = render(request, 'saas_core/onboarding_verify.html', {'pending': pending, 'error': error, 'completed': completed})
    response['Referrer-Policy'] = 'no-referrer'
    response['Cache-Control'] = 'no-store'
    return response
