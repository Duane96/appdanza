# apps/multimedia/models.py
from django.db import models
from apps.academias.models import Academia  # Tu modelo Tenant

class ModuloClase(models.Model):
    """Representa el título de la clase/módulo que aparece en el sidebar (Ej: Bachata Intensivo Nivel 1)"""
    academia = models.ForeignKey(Academia, on_delete=models.CASCADE, related_name='modulos_multimedia')
    titulo = models.CharField(max_length=200, verbose_name="Título del Módulo/Clase")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción General (Opcional)")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titulo} - {self.academia.nombre}"


class VideoClase(models.Model):
    """Representa cada uno de los videos individuales que pertenecen a un módulo."""
    modulo = models.ForeignKey(ModuloClase, on_delete=models.CASCADE, related_name='videos')
    titulo = models.CharField(max_length=200, verbose_name="Título del Video")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción del Video")
    
    # Aquí guardamos únicamente el ID (Ej: dQw4w9WgXcQ)
    youtube_id = models.CharField(max_length=100, verbose_name="YouTube Video ID")
    fecha_subida = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.titulo} ({self.modulo.titulo})"

    # --- PROPIEDADES DINÁMICAS (NO necesitan migración) ---

    @property
    def url_video(self):
        """Devuelve el enlace para compartir el video."""
        return f"https://www.youtube.com/watch?v={self.youtube_id}"

    @property
    def embed_url(self):
        """Devuelve el enlace directo para el reproductor (iframe)."""
        return f"https://www.youtube.com/embed/{self.youtube_id}"