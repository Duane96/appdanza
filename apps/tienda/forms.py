# apps/tienda/forms.py
from django import forms
from .models import CategoriaProducto, Producto, EntradaStock

class CategoriaProductoForm(forms.ModelForm):
    """Formulario para la creación de categorías en la tienda de la academia"""
    class Meta:
        model = CategoriaProducto
        fields = ['nombre', 'descripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Ropa, Bebidas, Accesorios'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class ProductoForm(forms.ModelForm):
    """Formulario para la administración de productos en el catálogo de inventario"""
    
    # NUEVO: Campo virtual para automatizar el ingreso del primer lote
    stock_inicial = forms.IntegerField(
        min_value=0, 
        initial=0, 
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        help_text="Opcional: Unidades iniciales al crear el producto."
    )

    class Meta:
        model = Producto
        fields = ['categoria', 'nombre', 'codigo_barras', 'precio_compra_actual', 'precio_venta_actual', 'stock_minimo', 'estado']
        widgets = {
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Camiseta Oficial'}),
            'codigo_barras': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'precio_compra_actual': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'precio_venta_actual': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'stock_minimo': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'estado': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        academia = kwargs.pop('academia', None)
        super().__init__(*args, **kwargs)
        if academia:
            self.fields['categoria'].queryset = CategoriaProducto.objects.filter(academia=academia)

    def __init__(self, *args, **kwargs):
        # Capturamos el tenant (academia) para filtrar únicamente las categorías del cliente actual
        academia = kwargs.pop('academia', None)
        super().__init__(*args, **kwargs)
        if academia:
            self.fields['categoria'].queryset = CategoriaProducto.objects.filter(academia=academia)


class EntradaStockForm(forms.ModelForm):
    """Formulario directo para reabastecer stock de un producto existente"""
    class Meta:
        model = EntradaStock
        fields = ['producto', 'cantidad', 'precio_compra']
        widgets = {
            'producto': forms.Select(attrs={'class': 'form-select'}),
            'cantidad': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'precio_compra': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'placeholder': 'Precio de compra unitario esta vez'}),
        }

    def __init__(self, *args, **kwargs):
        academia = kwargs.pop('academia', None)
        super().__init__(*args, **kwargs)
        if academia:
            # Solo permitimos dar entrada a productos activos y pertenecientes a esta academia
            self.fields['producto'].queryset = Producto.objects.filter(academia=academia, estado=True)