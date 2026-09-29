from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PerfilUsuario, TenantMembership


@receiver(post_save, sender=PerfilUsuario)
def membership_for_new_profile(sender, instance, created, **kwargs):
    if created and instance.academia_id:
        role = {'ADMIN_ACADEMIA': 'OWNER', 'PROFESOR': 'TEACHER', 'ESTUDIANTE': 'STUDENT'}.get(instance.rol)
        if role:
            TenantMembership.objects.get_or_create(user_id=instance.user_id, academia_id=instance.academia_id,
                                                   defaults={'role': role, 'source': 'PROFILE_CREATE'})
