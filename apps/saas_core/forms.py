# apps/saas_core/forms.py
from django import forms
from .models import ConfigPagoGlobalSaaS

class ConfigPagoSaaSForm(forms.ModelForm):
    """Formulario estilizado para la configuración del recaudo global."""
    class Meta:
        model = ConfigPagoGlobalSaaS
        fields = ['tipo_metodo', 'nombre_proveedor', 'identificador_pago', 'titular', 'documento_titular', 'instrucciones_adicionales']
        widgets = {
            'tipo_metodo': forms.Select(attrs={'class': 'form-select rounded-3'}),
            'nombre_proveedor': forms.TextInput(attrs={'class': 'form-control rounded-3', 'placeholder': 'Ej: Nequi o Bancolombia'}),
            'identificador_pago': forms.TextInput(attrs={'class': 'form-control rounded-3', 'placeholder': 'Número de cuenta, celular o llave'}),
            'titular': forms.TextInput(attrs={'class': 'form-control rounded-3', 'placeholder': 'Nombre completo del dueño'}),
            'documento_titular': forms.TextInput(attrs={'class': 'form-control rounded-3', 'placeholder': 'Cédula o NIT'}),
            'instrucciones_adicionales': forms.Textarea(attrs={'class': 'form-control rounded-3', 'rows': 2, 'placeholder': 'Instrucciones cortas...'}),
        }

# apps/saas_core/views.py
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views import View
from django.shortcuts import redirect
from django.contrib import messages
from .forms import ConfigPagoSaaSForm
from .models import ConfigPagoGlobalSaaS

class GuardarConfigPagoGlobalView(UserPassesTestMixin, View):
    """Vista del Panel Maestro para guardar/actualizar el método único de pago del SaaS."""
    def test_func(self):
        return self.request.user.is_superuser and self.request.user.is_staff

    def post(self, request, *args, **kwargs):
        # Implementación estilo Singleton: Traemos el único registro existente o inicializamos uno nuevo
        config_actual = ConfigPagoGlobalSaaS.objects.first()
        form = ConfigPagoSaaSForm(request.POST, instance=config_actual)
        
        if form.is_valid():
            form.save()
            messages.success(request, "¡Configuración de recaudo global actualizada correctamente!")
        else:
            messages.error(request, "Error al procesar el formulario de pagos.")
            
        return redirect('panel_maestro_dashboard')