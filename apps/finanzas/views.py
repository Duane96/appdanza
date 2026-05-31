# apps/finanzas/views.py
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic import ListView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.db import transaction
from django.contrib import messages
from django.utils import timezone

from .models import ReciboIngreso, Gasto
from .forms import GastoForm, LiquidacionProfesorForm, IngresoExtraForm

class PanelFinanzasView(LoginRequiredMixin, ListView):
    """Muestra el historial contable completo de la academia"""
    template_name = "finanzas/panel_finanzas.html"
    context_object_name = "gastos"

    def get_queryset(self):
        return Gasto.objects.filter(academia=self.request.tenant).order_by('-creado_en')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Traemos también los ingresos para pintarlos en pestañas o tablas separadas
        context['ingresos'] = ReciboIngreso.objects.filter(academia=self.request.tenant).order_by('-creado_en')
        return context

class RegistrarGastoView(LoginRequiredMixin, FormView):
    """Registro de egresos tradicionales"""
    template_name = "finanzas/registrar_gasto.html"
    form_class = GastoForm

    def form_valid(self, form):
        gasto = form.save(commit=False)
        gasto.academia = self.request.tenant
        gasto.save()
        messages.success(self.request, f"Comprobante de egreso {gasto.numero_egreso} creado correctamente.")
        return redirect('finanzas:panel_finanzas', slug_academia=self.request.tenant.slug)

class LiquidarProfesorView(LoginRequiredMixin, FormView):
    """Automatiza el documento soporte y pago de nómina de los profesores"""
    template_name = "finanzas/liquidar_profesor.html"
    form_class = LiquidacionProfesorForm

    def form_valid(self, form):
        data = form.cleaned_data
        monto_total = data['cantidad_clases'] * data['valor_clase']
        concepto_final = f"NÓMINA AUTOGENERADA: Pago de {data['cantidad_clases']} clases (${data['valor_clase']:,.0f} c/u). {data['detalles']}"

        # Insertamos automáticamente en la tabla Gasto como categoría NOMINA
        Gasto.objects.create(
            academia=self.request.tenant,
            categoria='NOMINA',
            concepto=concepto_final,
            monto=monto_total,
            fecha=data['fecha_pago'],
            proveedor_nit=data['profesor_nit'],
            proveedor_nombre=data['profesor_nombre']
        )
        messages.success(self.request, f"Liquidación de nómina generada con éxito por ${monto_total:,.0f} para {data['profesor_nombre']}.")
        return redirect('finanzas:panel_finanzas', slug_academia=self.request.tenant.slug)

class RegistrarIngresoExtraView(LoginRequiredMixin, FormView):
    """Permite facturar ingresos de la tienda, eventos, etc."""
    template_name = "finanzas/registrar_ingreso.html"
    form_class = IngresoExtraForm

    def form_valid(self, form):
        ingreso = form.save(commit=False)
        ingreso.academia = self.request.tenant
        ingreso.save()
        messages.success(self.request, f"Recibo de Caja {ingreso.numero_recibo} expedido con éxito.")
        return redirect('finanzas:panel_finanzas', slug_academia=self.request.tenant.slug)

class AnularTransaccionView(LoginRequiredMixin, View):
    """Pone en CERO el efecto contable de un recibo o gasto guardando el rastro legal"""
    def post(self, request, slug_academia, tipo, pk):
        motivo = request.POST.get('motivo_anulacion', 'No especificado')
        
        if tipo == 'ingreso':
            item = get_object_or_404(ReciboIngreso, pk=pk, academia=request.tenant)
            item.estado = 'ANULADO'
            item.motivo_anulacion = motivo
            item.anulado_por = request.user
            item.save()
            messages.warning(request, f"El Recibo de Caja {item.numero_recibo} ha sido ANULADO.")
            
        elif tipo == 'gasto':
            item = get_object_or_404(Gasto, pk=pk, academia=request.tenant)
            item.estado = 'ANULADO'
            item.motivo_anulacion = motivo
            item.anulado_por = request.user
            item.save()
            messages.warning(request, f"El Comprobante de Egreso {item.numero_egreso} ha sido ANULADO.")

        return redirect('finanzas:panel_finanzas', slug_academia=slug_academia)