"""Private uploads live outside MEDIA_ROOT and require a resource permission."""
import uuid
from io import BytesIO
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils.deconstruct import deconstructible
from django.views.decorators.http import require_GET
from .authorization import can, tenant_id_for

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.pdf'}
PRIVATE_FIELDS = (
    ('eventos.ReciboEvento', 'comprobante_pago'), ('eventos.EntradaQR', 'imagen_qr'),
    ('planes_estudiantes.Estudiante', 'qr_code'), ('finanzas.Gasto', 'soporte_digital'),
    ('saas_core.ReportePagoSaaS', 'comprobante'), ('saas_core.GastoSaaS', 'comprobante'),
)


def validate_private_upload(file):
    if not file:
        return
    extension = Path(file.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS or file.size > MAX_BYTES:
        raise ValidationError('Adjunta una imagen PNG/JPG/WebP o PDF de máximo 5 MB.')
    position = file.tell()
    try:
        file.seek(0)
        if extension == '.pdf':
            if not file.read(5).startswith(b'%PDF-'):
                raise ValidationError('El archivo no es un PDF válido.')
        else:
            from PIL import Image
            with Image.open(BytesIO(file.read())) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 25_000_000:
                    raise ValidationError('La imagen no es válida o es demasiado grande.')
                image.verify()
    except (OSError, ValueError):
        raise ValidationError('No se pudo validar el archivo.')
    finally:
        if not file.closed:
            file.seek(position)


@deconstructible
class PrivateStorage(FileSystemStorage):
    @property
    def base_location(self):
        return str(getattr(settings, 'PRIVATE_MEDIA_ROOT', settings.BASE_DIR / 'private_media'))

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def get_valid_name(self, name):
        return uuid.uuid4().hex + Path(name).suffix.lower()

    def url(self, name):
        return reverse('private_media', kwargs={'name': name})

    def _save(self, name, content):
        validate_private_upload(content)
        return super()._save(name, content)


private_storage = PrivateStorage()


@require_GET
def download(request, name):
    if '..' in Path(name).parts or Path(name).is_absolute():
        raise Http404
    for label, field in PRIVATE_FIELDS:
        model = apps.get_model(label)
        resource = model._base_manager.filter(**{field: name}).first()
        if resource is None:
            continue
        from .models import Academia
        tenant_id = tenant_id_for(resource)
        tenant = Academia.unfiltered_objects.filter(pk=tenant_id).first() if tenant_id else None
        allowed = can(request.user, tenant, 'tenant.admin') if tenant else can(request.user, None, 'platform.manage')
        if label == 'eventos.EntradaQR':
            from apps.eventos.receipt_access import can_read_receipt
            allowed = allowed or can_read_receipt(request, resource.recibo)
            if resource.revoked_at or resource.recibo.anulado:
                raise Http404
        if label == 'saas_core.ReportePagoSaaS':
            allowed = allowed or can(request.user, tenant, 'billing.manage')
        if label == 'planes_estudiantes.Estudiante':
            from .student_identity import student_for
            own_student = student_for(request.user, tenant)
            allowed = allowed or (own_student is not None and own_student.pk == resource.pk)
        if not allowed:
            raise PermissionDenied('No tienes acceso a este archivo.')
        file = getattr(resource, field)
        try:
            response = FileResponse(file.open('rb'), as_attachment=Path(name).suffix.lower() == '.pdf')
        except FileNotFoundError:
            raise Http404
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        return response
    raise Http404
