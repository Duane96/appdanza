from django.contrib import admin


class PlatformModelAdmin(admin.ModelAdmin):
    """Django admin is explicitly platform-wide and superuser-only."""
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def get_queryset(self, request):
        qs = self.model._base_manager.all()
        return qs if self.has_module_permission(request) else qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        kwargs['queryset'] = db_field.remote_field.model._base_manager.all() if self.has_module_permission(request) else db_field.remote_field.model._base_manager.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        from apps.saas_core.audit import record, sanitized_snapshot
        from .authorization import tenant_id_for
        from .models import Academia
        previous = self.model._base_manager.filter(pk=obj.pk).first() if change else None
        before = sanitized_snapshot(previous.__dict__) if previous else {}
        super().save_model(request, obj, form, change)
        tenant_id = tenant_id_for(obj)
        tenant = Academia.unfiltered_objects.filter(pk=tenant_id).first() if tenant_id else None
        record(tenant, request.user, 'platform.record.updated' if change else 'platform.record.created',
               f'{obj._meta.label_lower}:{obj.pk}', before=before, after=sanitized_snapshot(obj.__dict__))


class ReadOnlyPlatformAdmin(PlatformModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
