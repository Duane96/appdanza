# apps/planes_estudiantes/admin.py
from django.contrib import admin
from .models import Plan, Estudiante, InscripcionPlan

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'academia', 'precio', 'duracion_dias')
    def get_queryset(self, request): return Plan.unfiltered_objects.all()

@admin.register(Estudiante)
class EstudianteAdmin(admin.ModelAdmin):
    list_display = ('nombres', 'apellidos', 'academia', 'identificacion', 'estado')
    readonly_fields = ('qr_code', 'token_asistencia')
    def get_queryset(self, request): return Estudiante.unfiltered_objects.all()

@admin.register(InscripcionPlan)
class InscripcionPlanAdmin(admin.ModelAdmin):
    list_display = ('estudiante', 'plan', 'fecha_fin', 'clases_restantes')
    def get_queryset(self, request): return InscripcionPlan.unfiltered_objects.all()