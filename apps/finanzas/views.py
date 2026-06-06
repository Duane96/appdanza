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

import csv
from django.http import JsonResponse, HttpResponse
from datetime import datetime
from django.db.models import Sum
from datetime import date
import calendar

from itertools import chain
from operator import attrgetter


class PanelFinanzasView(LoginRequiredMixin, ListView):
    template_name = "finanzas/panel_finanzas.html"
    context_object_name = "gastos"

    def get_queryset(self):
        return Gasto.objects.filter(academia=self.request.tenant).order_by('-creado_en')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Definir rango del mes actual
        hoy = date.today()
        primer_dia = date(hoy.year, hoy.month, 1)
        ultimo_dia = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])
        
        # 2. Filtrar ingresos y gastos del mes
        ingresos_mes = ReciboIngreso.objects.filter(
            academia=self.request.tenant, 
            estado='ACTIVO',
            fecha__range=[primer_dia, ultimo_dia]
        )
        gastos_mes = Gasto.objects.filter(
            academia=self.request.tenant, 
            estado='ACTIVO',
            fecha__range=[primer_dia, ultimo_dia]
        )
        
        # 3. Cálculos agregados
        context['ingresos_totales_mes'] = ingresos_mes.aggregate(total=Sum('monto'))['total'] or 0
        context['gastos_totales_mes'] = gastos_mes.aggregate(total=Sum('monto'))['total'] or 0
        context['balance_mes'] = context['ingresos_totales_mes'] - context['gastos_totales_mes']
        
        # Datos para las tablas existentes
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
    

class ObtenerDetalleTransaccionView(LoginRequiredMixin, View):
    """
    Retorna los datos de un ingreso o gasto en formato JSON.
    Optimiza el DOM evitando renderizar modales por cada fila.
    """
    def get(self, request, slug_academia, tipo, pk):
        # Filtro estricto por Tenant (Academia) para asegurar aislamiento absoluto de datos
        if tipo == 'ingreso':
            item = ReciboIngreso.objects.filter(academia=request.tenant, pk=pk).first()
            if not item:
                return JsonResponse({'error': 'Recibo no encontrado'}, status=404)
            
            data = {
                'consecutivo': item.numero_recibo,
                'fecha': item.fecha.strftime('%d/%m/%Y'),
                'tipo_badge': item.get_tipo_ingreso_display(),
                'tercero_nombre': item.cliente_nombre,
                'tercero_nit': item.cliente_nit,
                'concepto': item.concepto,
                'medio_pago': item.get_medio_pago_display(),
                'monto': float(item.monto),
                'estado': item.estado,
                'tipo_transaccion': 'Ingreso de Caja'
            }
        elif tipo == 'gasto':
            item = Gasto.objects.filter(academia=request.tenant, pk=pk).first()
            if not item:
                return JsonResponse({'error': 'Comprobante no encontrado'}, status=404)
            
            data = {
                'consecutivo': item.numero_egreso,
                'fecha': item.fecha.strftime('%d/%m/%Y'),
                'tipo_badge': item.get_categoria_display(),
                'tercero_nombre': item.proveedor_nombre,
                'tercero_nit': item.proveedor_nit,
                'concepto': item.concepto,
                'medio_pago': 'N/A (Egreso)',
                'monto': float(item.monto),
                'estado': item.estado,
                'tipo_transaccion': 'Comprobante de Egreso'
            }
        else:
            return JsonResponse({'error': 'Tipo no válido'}, status=400)
            
        return JsonResponse(data)


class ExportarReporteContableView(LoginRequiredMixin, View):
    """
    Genera un archivo CSV estructurado contablemente con filtros de fechas.
    Es ultra ligero en memoria, ideal para los límites de PythonAnywhere.
    """
    def get(self, request, slug_academia):
        tipo_reporte = request.GET.get('tipo', 'diario')
        fecha_inicio_str = request.GET.get('fecha_inicio')
        fecha_fin_str = request.GET.get('fecha_fin')
        
        # Filtro base por Tenant
        ingresos = ReciboIngreso.objects.filter(academia=request.tenant)
        gastos = Gasto.objects.filter(academia=request.tenant)
        
        # Lógica de segmentación de fechas según el botón clickeado
        if tipo_reporte == 'diario' and fecha_inicio_str:
            fecha_dt = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            ingresos = ingresos.filter(fecha=fecha_dt)
            gastos = gastos.filter(fecha=fecha_dt)
            filename = f"reporte_diario_{fecha_inicio_str}.csv"
        elif tipo_reporte == 'mensual' and fecha_inicio_str and fecha_fin_str:
            f_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            ingresos = ingresos.filter(fecha__range=[f_inicio, f_fin])
            gastos = gastos.filter(fecha__range=[f_inicio, f_fin])
            filename = f"reporte_contable_{fecha_inicio_str}_al_{fecha_fin_str}.csv"
        else:
            return HttpResponse("Parámetros de fecha inválidos.", status=400)

        # Configuración del response HTTP para descarga de archivo
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig') # utf-8-sig para que Excel reconozca las tildes y eñes en Windows
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response, delimiter=';')
        
        # Encabezados aptos para cualquier software contable o revisión de la DIAN
        writer.writerow([
            'Fecha', 'Consecutivo', 'Tipo Transaccion', 'Categoria/Subtipo', 
            'Tercero Nombre', 'Tercero NIT/CC', 'Concepto', 'Medio de Pago', 
            'Ingreso (Debito)', 'Egreso (Credito)', 'Estado'
        ])
        
        # Escribir Ingresos
        for ing in ingresos.order_by('creado_en'):
            writer.writerow([
                ing.fecha.strftime('%d/%m/%Y'),
                ing.numero_recibo,
                'INGRESO',
                ing.get_tipo_income_display() if hasattr(ing, 'get_tipo_income_display') else ing.tipo_ingreso,
                ing.cliente_nombre,
                ing.cliente_nit,
                ing.concepto,
                ing.get_medio_pago_display(),
                ing.monto if ing.estado == 'ACTIVO' else 0, # Si está anulado, contablemente va en 0
                0,
                ing.estado
            ])
            
        # Escribir Gastos
        for gas in gastos.order_by('creado_en'):
            writer.writerow([
                gas.fecha.strftime('%d/%m/%Y'),
                gas.numero_egreso,
                'EGRESO',
                gas.get_categoria_display(),
                gas.proveedor_nombre,
                gas.proveedor_nit,
                gas.concepto,
                'Efectivo/Banco',
                0,
                gas.monto if gas.estado == 'ACTIVO' else 0,
                gas.estado
            ])
            
        return response
    

class ResumenReporteAjaxView(LoginRequiredMixin, View):
    """Retorna los totales y el listado de transacciones para previsualizar en el Modal"""
    def get(self, request, slug_academia):
        tipo = request.GET.get('tipo', 'diario')
        fecha_inicio = request.GET.get('fecha_inicio')
        fecha_fin = request.GET.get('fecha_fin')
        
        # 1. Filtramos las transacciones válidas (ACTIVAS)
        ingresos = ReciboIngreso.objects.filter(academia=request.tenant, estado='ACTIVO')
        gastos = Gasto.objects.filter(academia=request.tenant, estado='ACTIVO')
        
        if tipo == 'diario' and fecha_inicio:
            ingresos = ingresos.filter(fecha=fecha_inicio)
            gastos = gastos.filter(fecha=fecha_inicio)
        elif tipo == 'mensual' and fecha_inicio and fecha_fin:
            ingresos = ingresos.filter(fecha__range=[fecha_inicio, fecha_fin])
            gastos = gastos.filter(fecha__range=[fecha_inicio, fecha_fin])
            
        # 2. Cálculos rápidos
        tot_ing_dict = ingresos.aggregate(total=Sum('monto'))
        tot_gas_dict = gastos.aggregate(total=Sum('monto'))
        
        tot_ingresos = tot_ing_dict['total'] or 0
        tot_gastos = tot_gas_dict['total'] or 0
        balance = tot_ingresos - tot_gastos

        # 3. Construimos el listado unificado y ordenado por fecha de creación
        # itertools.chain une los dos QuerySets sin hacer consultas pesadas extra
        transacciones_db = sorted(
            chain(ingresos, gastos),
            key=attrgetter('creado_en'),
            reverse=True
        )
        
        lista_tx = []
        for tx in transacciones_db:
            es_ingreso = isinstance(tx, ReciboIngreso)
            lista_tx.append({
                'consecutivo': tx.numero_recibo if es_ingreso else tx.numero_egreso,
                'tercero': tx.cliente_nombre if es_ingreso else tx.proveedor_nombre,
                'concepto': tx.concepto,
                'monto': float(tx.monto),
                'tipo': 'ingreso' if es_ingreso else 'gasto',
                'fecha': tx.fecha.strftime('%d/%m/%Y')
            })
        
        return JsonResponse({
            'ingresos': float(tot_ingresos),
            'gastos': float(tot_gastos),
            'balance': float(balance),
            'cantidad_tx': len(lista_tx),
            'transacciones': lista_tx  # Enviamos el listado al frontend
        })