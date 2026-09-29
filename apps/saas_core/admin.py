from django.contrib import admin

# Register your models here.

from apps.academias.platform_admin import ReadOnlyPlatformAdmin
from .models import AuditEvent, DurableJob
from apps.academias.platform_admin import PlatformModelAdmin
from .models import (BillingAccount, PlanSaaS, PlanVersion, EventFeeRate, CommercialSubscription,
    SaaSInvoice, InvoiceLine, SaaSPayment, UsageEntry, SaaSCredit, SaaSRefund, ProviderEvent, PaymentAttempt)


@admin.register(BillingAccount)
class BillingAccountAdmin(PlatformModelAdmin):
    list_display = ('academia', 'mode', 'grant_until', 'automatic_charges_authorized')
    list_filter = ('mode',)
    readonly_fields = ('legacy_snapshot', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('academia',) if obj else ()) + (('mode', 'automatic_charges_authorized', 'grant_until') if obj and obj.mode == 'INTERNAL' else ())


@admin.register(PlanVersion, EventFeeRate)
class ImmutableConfigurationAdmin(PlatformModelAdmin):
    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(PlanSaaS, PlatformModelAdmin)
for model in (CommercialSubscription, SaaSInvoice, InvoiceLine, SaaSPayment, UsageEntry, SaaSCredit,
              SaaSRefund, ProviderEvent, PaymentAttempt):
    admin.site.register(model, ReadOnlyPlatformAdmin)

@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyPlatformAdmin):
    list_display = ('occurred_at', 'academia', 'action', 'resource', 'actor')
    list_filter = ('action', 'academia')

@admin.register(DurableJob)
class DurableJobAdmin(ReadOnlyPlatformAdmin):
    list_display = ('id', 'kind', 'academia', 'state', 'attempts', 'available_at', 'last_error')
    exclude = ('payload',)
    list_filter = ('state', 'kind')
