# apps/finanzas/forms.py
from django import forms
from .models import Gasto, ReciboIngreso

class GastoForm(forms.ModelForm):
    """Formulario para gastos comunes de la academia"""
    class Meta:
        model = Gasto
        fields = ['numero_factura_proveedor', 'categoria', 'concepto', 'monto', 'fecha', 'proveedor_nit', 'proveedor_nombre', 'soporte_digital']
        widgets = {
            'numero_factura_proveedor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: FE-102 (Opcional)'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Compra de insumos de aseo'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'placeholder': '0'}),
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'proveedor_nit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NIT o Cédula'}),
            'proveedor_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre o Razón Social'}),
            'soporte_digital': forms.FileInput(attrs={'class': 'form-control'}),
        }

class LiquidacionProfesorForm(forms.Form):
    """Formulario inteligente para calcular el sueldo del profesor sin cuenta de cobro"""
    profesor_nit = forms.CharField(max_length=50, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cédula del Profesor'}))
    profesor_nombre = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre Completo'}))
    cantidad_clases = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 8'}))
    valor_clase = forms.DecimalField(max_digits=10, decimal_places=0, initial=50000, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    fecha_pago = forms.DateField(widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    detalles = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': '2', 'placeholder': 'Ej: Pago clases de Salsa estilo Cali de las semanas 1 a 4'}))

class IngresoExtraForm(forms.ModelForm):
    """Formulario para ingresos varios (Venta de agua, camisetas, etc.)"""
    class Meta:
        model = ReciboIngreso
        fields = ['tipo_ingreso', 'concepto', 'monto', 'medio_pago', 'cliente_nit', 'cliente_nombre']
        widgets = {
            'tipo_ingreso': forms.Select(attrs={'class': 'form-select'}),
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Venta de 2 botellas de agua'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
            'medio_pago': forms.Select(attrs={'class': 'form-select'}),
            'cliente_nit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cédula de quien compra'}),
            'cliente_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del comprador'}),
        }