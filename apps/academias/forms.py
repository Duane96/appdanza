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
            'instagram_url', 'facebook_url', 'tiktok_url', 'youtube_url', 'whatsapp_url',
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
            'whatsapp_url': forms.URLInput(attrs={'class': 'form-control'}),
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
            'autocomplete': 'off'
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
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username is not None and password:
            real_username = username
            estudiante_detectado = None

            print("\n" + "="*50)
            print(f"🚀 INICIANDO DEBUG DE LOGIN (TENANT: {getattr(self.request, 'tenant', 'SIN TENANT')})")
            print(f"📥 Input recibido en formulario: '{username}'")
            print("="*50)

            # 1. 📧 ¿Ingresó un Email?
            if '@' in username:
                print("📧 Detectado intento por correo electrónico.")
                user_obj = User.objects.filter(email__iexact=username).first()
                if user_obj:
                    real_username = user_obj.username
                    print(f"✅ Correo encontrado. Username global asociado: '{real_username}'")
                else:
                    print("❌ Correo no encontrado en la base de datos global.")
            else:
                # 2. 🪪 ¿Ingresó su Documento de Identidad?
                if hasattr(self.request, 'tenant'):
                    from apps.planes_estudiantes.models import Estudiante 
                    from apps.academias.models import PerfilUsuario 
                    
                    print("🪪 Buscando si el input coincide con un documento en esta academia...")
                    estudiante_detectado = Estudiante.objects.filter(
                        identificacion=username, 
                        academia=self.request.tenant
                    ).first()
                    
                    if estudiante_detectado:
                        print(f"✅ ¡Estudiante encontrado localmente! -> {estudiante_detectado.nombres} {estudiante_detectado.apellidos} (ID: {estudiante_detectado.id})")
                        
                        perfiles_academia = PerfilUsuario.objects.filter(
                            academia=self.request.tenant, 
                            rol='ESTUDIANTE'
                        ).select_related('user')
                        
                        print(f"👥 Total de perfiles de estudiantes en esta academia: {perfiles_academia.count()}")

                        perfil_encontrado = None

                        if estudiante_detectado.email:
                            print(f"🔍 Buscando PerfilUsuario usando su email: {estudiante_detectado.email}")
                            perfil_encontrado = perfiles_academia.filter(user__email__iexact=estudiante_detectado.email).first()
                        
                        if not perfil_encontrado:
                            print("⚠️ No se encontró por email. Intentando reconstruir username...")
                            nombre_limpio = "".join(estudiante_detectado.nombres.split()).lower()
                            apellido_limpio = "".join(estudiante_detectado.apellidos.split()).lower()
                            base_username = f"{nombre_limpio}{apellido_limpio}"
                            base_username = "".join(c for c in unicodedata.normalize('NFD', base_username) if unicodedata.category(c) != 'Mn')
                            
                            print(f"🔍 Buscando PerfilUsuario cuyo username global comience con: '{base_username}'")
                            perfil_encontrado = perfiles_academia.filter(user__username__startswith=base_username).first()
                        
                        if perfil_encontrado:
                            real_username = perfil_encontrado.user.username
                            print(f"🎯 ¡BINGO! PerfilUsuario encontrado. Username real de Django es: '{real_username}'")
                        else:
                            print("🚨 ERROR CRÍTICO: Existe el modelo Estudiante, pero NO tiene un PerfilUsuario asociado en esta academia.")
                    else:
                        print("❌ No se encontró ningún estudiante con ese documento en ESTA academia.")

            # 3. 🔐 Intentamos autenticar
            print(f"🔐 Ejecutando authenticate() de Django con username='{real_username}'...")
            self.user_cache = authenticate(self.request, username=real_username, password=password)
            
            if self.user_cache is None:
                print("❌ authenticate() falló. Contraseña incorrecta o el usuario no existe/está inactivo.")
                if estudiante_detectado:
                    raise forms.ValidationError(
                        f"¡Hola {estudiante_detectado.nombres}! Encontramos tu perfil, pero la contraseña no coincide. "
                        f"(Tu verdadero nombre de usuario en esta academia es: '{real_username}')"
                    )
                raise self.get_invalid_login_error()
            else:
                print("✅ authenticate() EXITOSO. Validando autorización de Tenant...")
                self.confirm_login_allowed(self.user_cache)
                
                # 4. 🚀 BARRERA MULTI-TENANT
                if hasattr(self.request, 'tenant') and not self.user_cache.is_superuser:
                    try:
                        if self.user_cache.perfil.academia != self.request.tenant:
                            print(f"🚨 BLOQUEO MULTI-TENANT: El usuario pertenece a {self.user_cache.perfil.academia.nombre}, intentó entrar a {self.request.tenant.nombre}")
                            raise forms.ValidationError("No tienes acceso a esta academia. Verifica el enlace que te compartieron.")
                    except ObjectDoesNotExist:
                        print("🚨 BLOQUEO: El usuario no tiene perfil SaaS (ObjectDoesNotExist).")
                        raise forms.ValidationError("Este usuario no tiene un perfil SaaS asociado.")
                
                print("🎉 LOGIN COMPLETAMENTE APROBADO.")

        return self.cleaned_data