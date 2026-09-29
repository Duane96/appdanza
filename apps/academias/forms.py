# apps/academias/forms.py
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
import unicodedata
from .models import Academia

# -----------------------------------------------------------------------------
# 1. FORMULARIO DE CONFIGURACIÓN (Tuyo, intacto y perfecto)
# -----------------------------------------------------------------------------
class ConfigMascaraForm(forms.ModelForm):
    class Meta:
        model = Academia
        fields = [
            'nombre', 'logo', 'color_primario', 'color_secundario', 'telefono', 'nit',
            'hero_titulo', 'hero_eslogan', 'hero_imagen_1',
            'hero_titulo_2', 'hero_eslogan_2', 'hero_imagen_2',
            'info_titulo', 'info_descripcion_1', 'info_descripcion_2', 'info_imagen',
            'bloque_1_titulo', 'bloque_1_icono', 'bloque_2_titulo', 'bloque_2_icono',
            'bloque_3_titulo', 'bloque_3_icono', 'bloque_4_titulo', 'bloque_4_icono',
            'direccion_sede', 'horario_atencion', 
            'instagram_url', 'facebook_url', 'tiktok_url', 'youtube_url', 'whatsapp_numero',
            'login_imagen',
            'razon_social', 'nit', 'representante_legal', 'tipo_regimen', 'resolucion_facturacion'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'color_primario': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'color_secundario': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={'class': 'form-control'}),
            'hero_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'hero_eslogan': forms.TextInput(attrs={'class': 'form-control'}),
            'hero_imagen_1': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'hero_titulo_2': forms.TextInput(attrs={'class': 'form-control'}),
            'hero_eslogan_2': forms.TextInput(attrs={'class': 'form-control'}),
            'hero_imagen_2': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'info_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'info_descripcion_1': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'info_descripcion_2': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'info_imagen': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'direccion_sede': forms.TextInput(attrs={'class': 'form-control'}),
            'horario_atencion': forms.TextInput(attrs={'class': 'form-control'}),
            'instagram_url': forms.URLInput(attrs={'class': 'form-control'}),
            'facebook_url': forms.URLInput(attrs={'class': 'form-control'}),
            'tiktok_url': forms.URLInput(attrs={'class': 'form-control'}),
            'youtube_url': forms.URLInput(attrs={'class': 'form-control'}),
            'whatsapp_numero': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Ej: 573001234567'
            }),
            'login_imagen': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'bloque_1_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'bloque_1_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-1'}),
            'bloque_2_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'bloque_2_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-2'}),
            'bloque_3_titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'bloque_3_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-3'}),
            'bloque_4_titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'bloque_4_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-4'}),
            'razon_social': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Distrito Social S.A.S.'}),
            'nit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 900.123.456-7'}),
            'representante_legal': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de quien firma'}),
            'tipo_regimen': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: No responsable de IVA'}),
            'resolucion_facturacion': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 2, 
                'placeholder': 'Ej: Actividad económica 9329. Documento equivalente...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🚨 PARCHE DE PRODUCCIÓN 🚨
        # Esto fuerza a Django a aceptar el formulario aunque el cliente 
        # deje campos como "Sede" u "Horario" vacíos.
        for field in self.fields.values():
            field.required = False


# -----------------------------------------------------------------------------
# 2. 🚀 FORMULARIO DE LOGIN INTELIGENTE (MULTI-TENANT + OMNICANAL)
# -----------------------------------------------------------------------------
class TenantLoginForm(AuthenticationForm):
    """
    Formulario de autenticación Multi-Tenant con resolución inteligente de usuarios.
    """
    username = forms.CharField(
        label="Usuario, Correo o Documento",
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg rounded-pill', 
            'placeholder': 'Tu correo, documento o usuario',
            'autocomplete': 'username'
        })
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg rounded-pill', 
            'placeholder': 'Tu contraseña',
        })
    )

    def clean(self):
        from django.db.models import Q
        from .authorization import can
        from .models import TenantMembership
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        tenant = getattr(self.request, 'tenant', None)
        if username and password:
            actual = username
            if '@' in username and tenant:
                candidates = User.objects.filter(email__iexact=username).filter(
                    Q(tenant_memberships__academia=tenant, tenant_memberships__active=True) |
                    Q(eventos_colaborados__evento__academia=tenant)).distinct()
                # Never choose an arbitrary account sharing an email address.
                if candidates.count() == 1:
                    actual = candidates.get().username
            elif tenant:
                from apps.planes_estudiantes.models import Estudiante
                from .student_identity import user_for_student
                students = Estudiante.unfiltered_objects.filter(academia=tenant,
                    identificacion=username).select_related('user')
                if students.count() == 1:
                    account = user_for_student(students.get())
                    if account:
                        actual = account.username
            self.user_cache = authenticate(self.request, username=actual, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
            if tenant and not (can(self.user_cache, tenant, 'tenant.view') or
                               can(self.user_cache, tenant, 'events.view')):
                raise self.get_invalid_login_error()
        return self.cleaned_data
