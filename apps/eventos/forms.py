# apps/eventos/forms.py
from django import forms
from .models import Evento, CodigoDescuento, FasePreventa, ReciboEvento, GastoEvento

class EventoForm(forms.ModelForm):
    # 🚀 FIX SENIOR: Le decimos a Django "Tranquilo, yo me encargo de este campo si viene vacío"
    cantidad_dias = forms.IntegerField(required=False, initial=1)

    class Meta:
        model = Evento
        fields = [
            'nombre', 'imagen', 'fecha', 'fecha_fin', 'ubicacion', 
            'es_multidias', 'cantidad_dias', 'tiene_fases_fechas',
            'acepta_nequi_daviplata', 'numero_nequi_daviplata', 
            'acepta_banco_manual', 'datos_banco_manual', 
            'acepta_tarjetas_online'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'fecha_fin': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'es_multidias': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'tiene_pases_personalizados': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'tiene_fases_fechas': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'acepta_nequi_daviplata': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'numero_nequi_daviplata': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Nequi 312... o Llave'}),
            'acepta_banco_manual': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'datos_banco_manual': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'acepta_tarjetas_online': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    # 🧠 LÓGICA DE VALIDACIÓN INTELIGENTE
    def clean(self):
        cleaned_data = super().clean()
        es_multidias = cleaned_data.get('es_multidias')
        cantidad_dias = cleaned_data.get('cantidad_dias')

        if not es_multidias:
            cleaned_data['cantidad_dias'] = 1
        else:
            if not cantidad_dias or cantidad_dias < 1:
                self.add_error('cantidad_dias', 'Activaste evento de varios días. Debes indicar cuántos.')

        # 🧠 FORZAR ARQUITECTURA DE PASES: Todo evento usa pases por defecto.
        cleaned_data['tiene_pases_personalizados'] = True

        return cleaned_data


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



from .models import TipoPase

class TipoPaseForm(forms.ModelForm):
    class Meta:
        model = TipoPase
        fields = ['nombre', 'precio', 'accesos_permitidos']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Solo Social (Viernes)'}),
            'precio': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Dejar vacío si hay Fases de Fecha'}),
            'accesos_permitidos': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hacemos que el precio sea opcional a nivel backend
        self.fields['precio'].required = False

class FasePreventaForm(forms.ModelForm):
    class Meta:
        model = FasePreventa
        fields = ['nombre_fase', 'fecha_limite', 'precio_full', 'precio_dia']
        widgets = {
            'nombre_fase': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Early Bird 1'}),
            'fecha_limite': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'precio_full': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 150000'}),
            'precio_dia': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 80000'}),
        }