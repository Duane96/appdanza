from django import forms
from .models import Clase, SesionClase
from apps.profesores.models import Profesor

class ClaseForm(forms.ModelForm):
    """Formulario maestro para crear el concepto de la clase (Catálogo)."""
    class Meta:
        model = Clase
        fields = ['nombre', 'descripcion', 'tarifa_especifica', 'limite_cupos', 'color_calendario']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Ej: Clase enfocada en pasos libres...'}),
            'color_calendario': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
        }

    def __init__(self, tenant, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'color_calendario':
                field.widget.attrs.update({'class': 'form-control'})


class SesionClaseForm(forms.ModelForm):
    """Formulario para agendar una clase en el calendario con opción a repetir."""
    
    # 🚀 CAMPOS VIRTUALES PARA LA RECURRENCIA (No existen en el modelo)
    repetir_semanalmente = forms.BooleanField(
        required=False, initial=True, 
        label="¿Repetir semanalmente?",
        help_text="Generar múltiples clases a esta misma hora."
    )
    semanas_a_repetir = forms.IntegerField(
        required=False, initial=4, min_value=1, max_value=52, 
        label="¿Cuántas semanas seguidas?",
        help_text="Mínimo 1, Máximo 52 (1 año)."
    )

    class Meta:
        model = SesionClase
        fields = ['clase', 'profesor_asignado', 'fecha_hora_inicio', 'fecha_hora_fin']
        widgets = {
            'fecha_hora_inicio': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'fecha_hora_fin': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, tenant, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🛡️ SEGURIDAD TENANT
        self.fields['clase'].queryset = Clase.objects.filter(academia=tenant)
        self.fields['clase'].empty_label = "Seleccione la materia..."
        
        self.fields['profesor_asignado'].queryset = Profesor.objects.filter(academia=tenant, activo=True)
        self.fields['profesor_asignado'].empty_label = "Seleccione al instructor..."
        
        for field_name, field in self.fields.items():
            if field_name not in ['repetir_semanalmente']:
                field.widget.attrs['class'] = 'form-control'
            if field_name == 'repetir_semanalmente':
                field.widget.attrs['class'] = 'form-check-input'


class ExcepcionSesionForm(forms.ModelForm):
    """Formulario para modificar una sesión específica (Override)."""
    class Meta:
        model = SesionClase
        fields = ['estado', 'profesor_reemplazo', 'notas_excepcion']
        widgets = {
            'notas_excepcion': forms.TextInput(attrs={'placeholder': 'Ej: Clase enfocada en musicalidad...'}),
        }

    def __init__(self, tenant, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🛡️ Solo profesores de la academia actual
        self.fields['profesor_reemplazo'].queryset = Profesor.objects.filter(academia=tenant, activo=True)
        self.fields['profesor_reemplazo'].empty_label = "Sin reemplazo (Mismo profesor)"
        
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})