from functools import wraps
from django.db import transaction
from django.core.exceptions import ValidationError
from apps.academias.locks import lock_tenant
from .models import BillingAccount
from .policy import EntitlementService


def creation_guard(module, capacity=None):
    def decorate(method):
        @wraps(method)
        def guarded(self, form):
            try:
                with transaction.atomic():
                    lock_tenant(self.request.tenant)
                    if BillingAccount.objects.filter(academia=self.request.tenant).exists():
                        service = EntitlementService(self.request.tenant)
                        service.require(module, creating=True)
                        if capacity:
                            service.require_capacity(capacity)
                    return method(self, form)
            except ValidationError as exc:
                form.add_error(None, exc)
                return self.form_invalid(form)
        return guarded
    return decorate
