# apps/tienda/models.py
from django.db import models
from django.db.models import Sum
from apps.academias.models import Academia
from apps.finanzas.models import ReciboIngreso
from django.contrib.auth.models import User

class CategoriaProducto(models.Model):
    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='categorias_tienda')
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        # Evita que una academia cree dos categorías con el mismo nombre
        unique_together = ('academia', 'nombre')

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='productos')
    categoria = models.ForeignKey(CategoriaProducto, on_delete=models.SET_NULL, null=True, related_name='productos')

    nombre = models.CharField(max_length=150)
    codigo_barras = models.CharField(max_length=100, blank=True, null=True, help_text="Opcional: Para escáner o referencia rápida")

    precio_compra_actual = models.DecimalField(max_digits=10, decimal_places=2, help_text="Costo para la academia")
    precio_venta_actual = models.DecimalField(max_digits=10, decimal_places=2, help_text="Precio para el alumno")

    stock = models.IntegerField(default=0)
    stock_minimo = models.IntegerField(default=5, help_text="Para alertar cuando se esté acabando")

    estado = models.BooleanField(default=True, help_text="Desmarcar para ocultar del POS si ya no se vende")
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} - Stock: {self.stock}"

    @property
    def ganancia_estimada(self):
        return self.precio_venta_actual - self.precio_compra_actual


class EntradaStock(models.Model):
    """
    Registra cuando se compran nuevos productos para reabastecer el inventario.
    Mantiene el historial de a cómo se compró en determinada fecha.
    """
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='entradas')
    cantidad = models.PositiveIntegerField()
    precio_compra = models.DecimalField(max_digits=10, decimal_places=2, help_text="A cómo se compró esta vez")
    fecha = models.DateTimeField(auto_now_add=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        # Si es una entrada nueva, sumamos al stock del producto y actualizamos su costo base
        if is_new:
            self.producto.stock += self.cantidad
            self.producto.precio_compra_actual = self.precio_compra
            self.producto.save()

    def __str__(self):
        return f"+{self.cantidad} {self.producto.nombre} el {self.fecha.strftime('%d/%m/%Y')}"


class VentaTienda(models.Model):
    """
    Cabecera de la venta. Se relaciona con la app de Finanzas para la contabilidad general.
    """
    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='ventas_tienda')

    # 🔗 Conexión directa a la contabilidad general (Uno a Uno)
    recibo_caja = models.OneToOneField(
        ReciboIngreso,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='venta_origen'
    )

    fecha = models.DateTimeField(auto_now_add=True)
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    total_venta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_ganancia = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"Venta #{self.id} - ${self.total_venta} ({self.fecha.strftime('%d/%m/%Y')})"


class DetalleVenta(models.Model):
    """
    Los items individuales dentro de una VentaTienda (El carrito de compras)
    """
    venta = models.ForeignKey(VentaTienda, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT) # PROTECT evita borrar un producto si ya se vendió

    cantidad = models.PositiveIntegerField()

    # Guardamos los precios exactos al momento de la venta por si a futuro cambian los precios del producto
    precio_unitario_venta = models.DecimalField(max_digits=10, decimal_places=2)
    costo_unitario_compra = models.DecimalField(max_digits=10, decimal_places=2)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    ganancia = models.DecimalField(max_digits=12, decimal_places=2, editable=False)

    def save(self, *args, **kwargs):
        # Cálculos automáticos antes de guardar la línea
        self.subtotal = self.cantidad * self.precio_unitario_venta
        self.ganancia = self.cantidad * (self.precio_unitario_venta - self.costo_unitario_compra)

        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Descontar del stock automáticamente
        if is_new:
            self.producto.stock -= self.cantidad
            self.producto.save()

            # Actualizar los totales de la Venta maestra
            self.venta.total_venta = self.venta.detalles.aggregate(total=Sum('subtotal'))['total'] or 0
            self.venta.total_ganancia = self.venta.detalles.aggregate(ganancia=Sum('ganancia'))['ganancia'] or 0
            self.venta.save()



# ¡ESTAS DOS LÍNEAS SON OBLIGATORIAS!
from django.db.models.signals import pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=ReciboIngreso)
def restaurar_stock_por_recibo_anulado(sender, instance, **kwargs):
    """
    Escucha cada vez que se va a guardar un ReciboIngreso.
    Si detecta que el estado va a cambiar a 'ANULADO', verifica si viene de la tienda
    y devuelve las cantidades al stock físico de los productos.
    """
    # 1. Validamos que el recibo ya exista en BD (que no sea uno nuevo creándose)
    if instance.pk:
        try:
            # Consultamos cómo estaba el recibo en la base de datos ANTES de este guardado
            recibo_viejo = ReciboIngreso.objects.get(pk=instance.pk)

            # 2. Verificamos la transición exacta: Estaba ACTIVO y ahora viene ANULADO
            if recibo_viejo.estado == 'ACTIVO' and instance.estado == 'ANULADO':

                # 3. Revisamos si este recibo está conectado a una VentaTienda (gracias al related_name)
                if hasattr(instance, 'venta_origen'):
                    venta = instance.venta_origen

                    # 4. Iteramos sobre los detalles (el carrito de esa venta)
                    for detalle in venta.detalles.all():
                        # Devolvemos el producto a la estantería (Sumamos el stock)
                        detalle.producto.stock += detalle.cantidad
                        detalle.producto.save()

        except ReciboIngreso.DoesNotExist:
            # Si por alguna razón no existe el viejo, no hacemos nada
            pass