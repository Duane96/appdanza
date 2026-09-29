from django import forms
from .models import Profesor

class ProfesorForm(forms.ModelForm):
    # Nombre y Apellido siguen siendo virtuales porque van directo al modelo User de Django
    nombre = forms.CharField(max_length=150, required=True, label="Nombre del Profesor")
    apellido = forms.CharField(max_length=150, required=True, label="Apellido")
    email = forms.EmailField(required=True, label='Correo para la invitación de acceso')

    class Meta:
        model = Profesor
        # AHORA SÍ incluimos el documento porque ya existe en el modelo Profesor
        fields = ['nombre', 'apellido', 'email', 'documento_identidad', 'telefono', 'tipo_pago', 'tarifa_base']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🎨 Inyección de Bootstrap para UX Móvil
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control mb-3'})
