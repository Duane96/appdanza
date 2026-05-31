# apps/academias/forms.py
from django import forms
from .models import Academia

# apps/academias/forms.py

class ConfigMascaraForm(forms.ModelForm):
    class Meta:
        model = Academia
        # 🚨 Agregamos 'login_imagen' al final de la lista de campos procesados
        fields = [
            'nombre', 'logo', 'color_primario', 'color_secundario', 'telefono', 'nit',
            'hero_titulo', 'hero_eslogan', 'hero_imagen_1',
            'hero_titulo_2', 'hero_eslogan_2', 'hero_imagen_2',
            'info_titulo', 'info_descripcion_1', 'info_descripcion_2', 'info_imagen',
            'bloque_1_titulo', 'bloque_1_icono', 'bloque_2_titulo', 'bloque_2_icono',
            'bloque_3_titulo', 'bloque_3_icono', 'bloque_4_titulo', 'bloque_4_icono',
            'direccion_sede', 'horario_atencion', 
            'instagram_url', 'facebook_url', 'tiktok_url', 'youtube_url', 'whatsapp_url',
            'login_imagen'
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

            # 🚗 NUEVO WIDGET: Campo de archivo para la envoltura del login
            'login_imagen': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),

            # Selector Desplegable de los 4 bloques
            'bloque_1_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'bloque_1_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-1'}),
            'bloque_2_titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'bloque_2_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-2'}),
            'bloque_3_titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'bloque_3_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-3'}),
            'bloque_4_titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'bloque_4_icono': forms.Select(attrs={'class': 'form-select', 'id': 'select-icono-4'}),
        }