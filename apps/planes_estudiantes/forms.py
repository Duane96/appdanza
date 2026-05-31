# apps/planes_estudiantes/forms.py
from django import forms
from .models import Estudiante, Plan, InscripcionPlan



class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['nombre', 'descripcion', 'precio', 'duracion_dias', 'clases_totales']
        
        # 🎨 INYECCIÓN DE UI/UX: Widgets de Bootstrap 5
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Tiquetera Mensual Pro'
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Detalla brevemente qué beneficios incluye este paquete...',
                'rows': 3  # Acorta el tamaño gigante por defecto del textarea
            }),
            'precio': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 150000',
                'step': '100' # Ayuda a que las flechitas del input suban de 100 en 100
            }),
            'duracion_dias': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 30'
            }),
            'clases_totales': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 8'
            }),
        }


# apps/planes_estudiantes/forms.py

# apps/planes_estudiantes/forms.py

class EstudianteForm(forms.ModelForm):
    class Meta:
        model = Estudiante
        fields = ['nombres', 'apellidos', 'identificacion', 'email', 'telefono']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🚀 FORMA CORRECTA: Aplicamos la clase de Bootstrap a todos los inputs dinámicamente
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


# apps/planes_estudiantes/forms.py

class InscripcionPlanForm(forms.ModelForm):
    # 🚀 Solo dejamos el monto pagado y el medio de pago. Cero cédulas repetidas.
    monto_pagado = forms.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        initial=0, 
        label="Monto Pagado ($ COP)",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    
    medio_pago = forms.ChoiceField(
        choices=[
            ('EFECTIVO', 'Efectivo'),
            ('TRANSFERENCIA', 'Transferencia Bancaria (Nequi/Daviplata/Bancolombia)'),
            ('TARJETA', 'Tarjeta de Crédito / Débito'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    fecha_fin = forms.DateField(
        label="Fecha de Vencimiento",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    class Meta:
        model = InscripcionPlan
        fields = ['estudiante', 'plan', 'fecha_inicio', 'fecha_fin', 'monto_pagado']
        widgets = {
            'estudiante': forms.Select(attrs={'class': 'form-select'}),
            'plan': forms.Select(attrs={'class': 'form-select'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['estudiante'].queryset = Estudiante.objects.filter(academia=tenant)
            self.fields['plan'].queryset = Plan.objects.filter(academia=tenant)

    def clean(self):
        cleaned_data = super().clean()
        plan = cleaned_data.get('plan')
        monto_pagado = cleaned_data.get('monto_pagado')

        if plan and monto_pagado is not None:
            if monto_pagado > plan.precio:
                raise forms.ValidationError({
                    'monto_pagado': f"El monto pagado no puede ser mayor al precio del plan."
                })
        return cleaned_data