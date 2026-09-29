"""The only source of commercial exemptions, entitlements and restrictions."""
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.utils import timezone
from .models import BillingAccount, CommercialSubscription

MODULES = ('estudiantes', 'profesores', 'calendario', 'eventos', 'finanzas', 'multimedia', 'asistencias', 'tienda')


def legacy_features(subscription):
    if not subscription:
        return {name: False for name in MODULES}
    features = {}
    for name in MODULES:
        if name == 'eventos':
            features[name] = subscription.es_cuenta_partner_gratis or not subscription.bloqueo_manual_eventos
        else:
            plan_name = 'permite_asistencias_qr' if name == 'asistencias' else 'permite_' + name
            features[name] = not getattr(subscription, 'bloqueo_manual_' + name, False) and (
                subscription.es_cuenta_partner_gratis or bool(getattr(subscription.plan, plan_name, False)))
    features['max_students'] = None if subscription.es_cuenta_partner_gratis else getattr(subscription.plan, 'max_estudiantes', None)
    return features


class BillingPolicy:
    def __init__(self, tenant):
        self.tenant = tenant
        self.account = BillingAccount.objects.filter(academia=tenant).first()
        self.subscription = CommercialSubscription.objects.select_related('plan_version').filter(academia=tenant).first()

    @property
    def exempt(self):
        # Missing policy is never an authorization to invent a charge.
        return not self.account or self.account.mode != 'PAID'

    @property
    def can_invoice(self):
        return not self.exempt and self.subscription is not None and self.subscription.accepted_at is not None

    @property
    def can_automatically_charge(self):
        return self.can_invoice and self.account.automatic_charges_authorized and self.subscription.state not in ('TRIAL', 'CANCELLED')

    @property
    def features(self):
        if self.account:
            if self.account.mode != 'PAID':
                return self.account.grant_features
            if self.subscription:
                return self.subscription.plan_version.features
            return {}
        try:
            return legacy_features(self.tenant.suscripcion_saas)
        except ObjectDoesNotExist:
            return {}

    @property
    def restricted(self):
        if not self.account or self.account.mode in ('INTERNAL', 'LEGACY'):
            return False
        if self.account.mode in ('COMPLIMENTARY', 'TRIAL'):
            return bool(self.account.grant_until and self.account.grant_until < timezone.now())
        return not self.subscription or self.subscription.state in ('LIMITED', 'SUSPENDED', 'CANCELLED')


class EntitlementService:
    def __init__(self, tenant):
        self.tenant = tenant
        self.policy = BillingPolicy(tenant)

    def has(self, feature):
        return bool(self.policy.features.get(feature, False))

    def require(self, feature, *, creating=False):
        if not self.has(feature):
            raise PermissionDenied('Tu acceso actual no incluye este módulo. Consulta el plan con el propietario.')
        if creating and self.policy.restricted:
            raise PermissionDenied('El plan requiere revisión antes de crear nuevos registros. Tus datos se conservan.')

    def usage(self, feature):
        from apps.planes_estudiantes.models import Estudiante
        from apps.profesores.models import Profesor
        from apps.eventos.models import Evento
        models = {'max_students': Estudiante, 'max_teachers': Profesor, 'max_events': Evento}
        model = models.get(feature)
        if model is None:
            raise ValidationError('Límite desconocido.')
        qs = model._base_manager.filter(academia=self.tenant)
        if feature == 'max_events':
            qs = qs.exclude(estado='FINALIZADO')
        return qs.count()

    def require_capacity(self, feature, quantity=1):
        limit = self.policy.features.get(feature)
        if limit is not None and self.usage(feature) + quantity > int(limit):
            raise ValidationError('Alcanzaste el límite de tu plan. No se elimina ningún registro existente.')
