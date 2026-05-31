# apps/multimedia/forms.py
from django import forms
from .models import VideoClase, ModuloClase

class VideoClaseForm(forms.ModelForm):
    # Campo opcional: no se guarda en BD, solo sirve para el input visual
    archivo_video = forms.FileField(
        required=False, 
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'video/*'})
    )

    class Meta:
        model = VideoClase
        fields = ['modulo', 'titulo', 'descripcion'] # Solo los campos de la BD
        widgets = {
            'modulo': forms.Select(attrs={'class': 'form-select'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Paso Básico de Bachata'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        academia = kwargs.pop('academia', None)
        super().__init__(*args, **kwargs)
        if academia:
            self.fields['modulo'].queryset = ModuloClase.objects.filter(academia=academia)

class ModuloClaseForm(forms.ModelForm):
    class Meta:
        model = ModuloClase
        fields = ['titulo', 'descripcion']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Bachata Sensual Nivel 1'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Breve descripción de lo que aprenderán en este módulo...'}),
        }