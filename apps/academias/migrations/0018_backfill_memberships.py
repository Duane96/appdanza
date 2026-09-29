from django.db import migrations


def backfill(apps, schema_editor):
    Profile = apps.get_model('academias', 'PerfilUsuario')
    Membership = apps.get_model('academias', 'TenantMembership')
    roles = {'ADMIN_ACADEMIA': 'OWNER', 'PROFESOR': 'TEACHER', 'ESTUDIANTE': 'STUDENT'}
    for profile in Profile.objects.using(schema_editor.connection.alias).exclude(academia_id=None).iterator():
        role = roles.get(profile.rol)
        if role:
            Membership.objects.using(schema_editor.connection.alias).get_or_create(
                user_id=profile.user_id, academia_id=profile.academia_id,
                defaults={'role': role, 'active': True, 'source': 'LEGACY_PROFILE'})


class Migration(migrations.Migration):
    dependencies = [('academias', '0017_tenant_memberships')]
    # Reversing must not erase memberships that have subsequently been edited.
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
