# apps/eventos/forms.py
from django import forms
from .models import Evento, CodigoDescuento, ReciboEvento, GastoEvento

class EventoForm(forms.ModelForm):
    class Meta:
        model = Evento
        # 🎯 REPARACIÓN SENIOR: Reemplazamos 'datos_pago_instrucciones' por los nuevos campos estructurados
        fields = [
            'nombre', 'imagen', 'fecha', 'fecha_fin', 'ubicacion', 
            'es_multidias', 'cantidad_dias', 'precio_preventa', 'precio_puerta', # <--- AGREGA ESTO
            'precio_por_dia', 
            'acepta_nequi_daviplata', 'numero_nequi_daviplata', 
            'acepta_banco_manual', 'datos_banco_manual', 
            'acepta_tarjetas_online', 'terminos_condiciones'
        ]
        
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            # 🎯 REPARACIÓN SENIOR: format='%Y-%m-%dT%H:%M' fuerza la sintaxis compatible con HTML5
            'fecha': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control', 'type': 'datetime-local'}
            ),
            'fecha_fin': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'class': 'form-control', 'type': 'datetime-local'}
            ),
            'es_multidias': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'cantidad_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'precio_preventa': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Precio Full Pass'}),
            'precio_puerta': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '40000'}), # <--- AGREGA ESTO
            'precio_por_dia': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Precio por día individual'}),
            
            # 🇨🇴 INTERRUPTORES Y CAMPOS DE CONTROL LOCAL COLOMBIA / INTERNACIONAL
            'acepta_nequi_daviplata': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'numero_nequi_daviplata': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Nequi 3123456789 o Llave Alianza'}),
            
            'acepta_banco_manual': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'datos_banco_manual': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ej: Bancolombia Ahorros N° 123... Cédula Titular'}),
            
            'acepta_tarjetas_online': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            
            'terminos_condiciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class CodigoDescuentoForm(forms.ModelForm):
    class Meta:
        model = CodigoDescuento
        # 🎯 Añadimos 'precio_especial_dia' a los campos permitidos
        fields = ['nombre_codigo', 'precio_especial', 'precio_especial_dia', 'limite_usos', 'fecha_caducidad']
        widgets = {
            'nombre_codigo': forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': 'Ej: PROMO25K'}),
            'precio_especial': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '25000 (Pase Full)'}),
            
            # 🎯 Nuevo widget para el descuento de 1 día
            'precio_especial_dia': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 15000 (Solo para 1 Día)'}),
            
            'limite_usos': forms.NumberInput(attrs={'class': 'form-control'}),
            'fecha_caducidad': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }


class GastoEventoForm(forms.ModelForm):
    class Meta:
        model = GastoEvento
        fields = ['concepto', 'monto']
        widgets = {
            'concepto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Pago de DJ o Sonido'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '150000'}),
        }


class RegistroOnlineEventoForm(forms.ModelForm):
    """El formulario dinámico público para que la gente se inscriba desde la web."""
    codigo_cupon = forms.CharField(
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control text-uppercase', 'placeholder': '¿Tienes un código de descuento?'})
    )

    class Meta:
        model = ReciboEvento
        fields = ['comprador_nombre', 'comprador_correo', 'comprador_telefono', 'cantidad_entradas', 'comprobante_pago']
        widgets = {
            'comprador_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre completo'}),
            'comprador_correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@ejemplo.com'}),
            'comprador_telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 3123456789'}),
            'cantidad_entradas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
            'comprobante_pago': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'required': True}),
        }


class VentaPuertaForm(forms.ModelForm):
    """El formulario para que Duane/Aleja registren ventas manuales en la taquilla física."""
    class Meta:
        model = ReciboEvento
        fields = ['comprador_nombre', 'comprador_telefono', 'cantidad_entradas', 'precio_unitario_aplicado', 'medio_pago']
        widgets = {
            'comprador_nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del asistente'}),
            'comprador_telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Celular (Opcional)'}),
            'cantidad_entradas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'id': 'puerta_cantidad'}),
            'precio_unitario_aplicado': forms.NumberInput(attrs={'class': 'form-control', 'id': 'puerta_precio_unitario'}),
            'medio_pago': forms.Select(attrs={'class': 'form-select'}),
        }