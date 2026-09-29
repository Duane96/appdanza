from django.db import migrations


MODULES = ('estudiantes', 'profesores', 'calendario', 'eventos', 'finanzas', 'multimedia', 'asistencias', 'tienda')


def migrate_access(apps, schema_editor):
    Academy = apps.get_model('academias', 'Academia')
    Legacy = apps.get_model('saas_core', 'SuscripcionAcademia')
    Account = apps.get_model('saas_core', 'BillingAccount')
    Version = apps.get_model('saas_core', 'PlanVersion')
    Plan = apps.get_model('saas_core', 'PlanSaaS')
    db = schema_editor.connection.alias
    for plan in Plan.objects.using(db).all():
        features = {name: bool(getattr(plan, 'permite_asistencias_qr' if name == 'asistencias' else 'permite_'+name, False)) for name in MODULES}
        features['max_students'] = plan.max_estudiantes
        Version.objects.using(db).get_or_create(plan=plan, version=1, defaults={'name': plan.nombre,
            'amount': plan.precio_mensual, 'currency': 'COP', 'interval_months': 1,
            'features': features, 'published': False})
    for tenant in Academy.objects.using(db).all():
        legacy = Legacy.objects.using(db).filter(academia=tenant).select_related('plan').first()
        features = {}
        for name in MODULES:
            partner = bool(legacy and legacy.es_cuenta_partner_gratis)
            blocked = bool(legacy and getattr(legacy, 'bloqueo_manual_'+name, False))
            plan_feature = bool(legacy and legacy.plan and getattr(legacy.plan,
                'permite_asistencias_qr' if name == 'asistencias' else 'permite_'+name, False))
            features[name] = (partner or not blocked) if name == 'eventos' and legacy else (not blocked and (partner or plan_feature))
        features['max_students'] = None if not legacy or legacy.es_cuenta_partner_gratis else getattr(legacy.plan, 'max_estudiantes', None)
        mode = 'COMPLIMENTARY' if legacy and legacy.es_cuenta_partner_gratis else 'LEGACY'
        reason = 'Migración conservadora de acceso existente; sin contratación ni cargos retroactivos.'
        workspace = 'EVENT_ORGANIZER' if tenant.es_solo_eventos else 'ACADEMY'
        # Identification is migration-only. Runtime policies never branch on a tenant ID/slug.
        if tenant.slug == 'bachatamania':
            mode, workspace = 'INTERNAL', 'INTERNAL'
            reason = 'Tenant interno del propietario: suscripción y tarifas de eventos exentas permanentemente.'
        elif tenant.slug == 'bachatop':
            mode = 'COMPLIMENTARY'
            reason = 'Acceso externo concedido a Luis y Camila. Fin gratuito no inequívoco: pendiente de definición; no cobrar ni suspender.'
        Account.objects.using(db).get_or_create(academia=tenant, defaults={'mode': mode, 'grant_features': features,
            'grant_until': None, 'grant_reason': reason, 'automatic_charges_authorized': False,
            'legacy_snapshot': {'subscription_id': legacy.pk if legacy else None,
                'state': legacy.estado if legacy else None,
                'start': str(legacy.fecha_inicio) if legacy else None,
                'end': str(legacy.fecha_vencimiento) if legacy else None,
                'partner': bool(legacy and legacy.es_cuenta_partner_gratis)}})
        Academy.objects.using(db).filter(pk=tenant.pk).update(workspace_type=workspace)


class Migration(migrations.Migration):
    dependencies = [('saas_core', '0021_commercial_ledger'), ('academias', '0020_commercial_ledger')]
    operations = [migrations.RunPython(migrate_access, migrations.RunPython.noop)]
