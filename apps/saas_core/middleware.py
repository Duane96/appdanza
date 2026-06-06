from django.shortcuts import redirect
from django.contrib import messages
from django.http import Http404

class TenantLicensingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Ignoramos las consolas maestras y el Django admin para no bloquearte a ti mismo
        if request.path.startswith('/master/') or request.path.startswith('/admin/'):
            return self.get_response(request)

        # 2. Si la petición está dentro del ecosistema de una escuela de baile
        if hasattr(request, 'tenant') and request.tenant:
            try:
                suscripcion = request.tenant.suscripcion_saas
                
                # 🚫 CONTROL DE SUSPENSIÓN TOTAL
                if suscripcion.estado == 'SUSPENDIDO' and not request.path == f"/{request.tenant.slug}/":
                    if request.path.startswith(f"/{request.tenant.slug}/dashboard/") or request.path.startswith(f"/{request.tenant.slug}/login/"):
                        raise Http404("Esta academia se encuentra suspendida temporalmente por la administración de la plataforma.")

                # 🚫 CONTROL MODULAR MULTIMEDIA (Clases Virtuales / Cursos)
                if 'multimedia' in request.path:
                    if not suscripcion.plan.permite_multimedia or suscripcion.bloqueo_manual_multimedia:
                        messages.error(request, "El módulo de Clases Virtuales no está disponible en tu plan contratado.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)

                # 🚫 CONTROL MODULAR FINANZAS / CONTABILIDAD DIAN
                if 'finanzas' in request.path:
                    if not suscripcion.plan.permite_finanzas or suscripcion.bloqueo_manual_finanzas:
                        messages.error(request, "Acceso restringido al módulo financiero.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)

                # 🚫 CONTROL MODULAR ASISTENCIAS QR
                if 'asistencias' in request.path:
                    if not suscripcion.plan.permite_asistencias_qr or suscripcion.bloqueo_manual_asistencias:
                        messages.error(request, "Acceso restringido al módulo de asistencias por escáner QR.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)
                    
                # 🚫 CONTROL MODULAR ESTUDIANTES Y PLANES
                if 'estudiantes' in request.path or 'planes' in request.path:
                    if not suscripcion.plan.permite_estudiantes or suscripcion.bloqueo_manual_estudiantes:
                        messages.error(request, "Acceso restringido al módulo de estudiantes y tiqueteras.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)

                # 🚫 CONTROL MODULAR GESTIÓN DE EVENTOS Y CRÉDITOS
                if 'eventos' in request.path:
                    # Filtro base: si el plan no tiene eventos contratados
                    if not suscripcion.plan.permite_eventos or suscripcion.bloqueo_manual_eventos:
                        messages.error(request, "Acceso restringido al módulo de gestión de eventos.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)
                    
                if 'tienda' in request.path:
                    if not suscripcion.plan.permite_tienda or suscripcion.bloqueo_manual_tienda:
                        messages.error(request, "El módulo de Tienda e Inventarios no está habilitado en su licencia actual.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)
                    
                    # Filtro Anti-Fraude: Obligados a registrar su tarjeta de respaldo/garantía para crear eventos,
                    # excepto si están navegando justamente en la pantalla de configuración intentando ponerla.
                    if not request.tenant.tarjeta_respaldo_configurada and not 'configuracion' in request.path:
                        messages.warning(request, "Atención: Debes vincular una tarjeta de respaldo activa en tu Panel de Configuración antes de poder gestionar o aperturar tus Eventos.")

            except Exception:
                # Si la base de datos se desalinea y la academia quedó huérfana de plan
                if not request.path == f"/{request.tenant.slug}/":
                    raise Http404("La academia no cuenta con una licencia SaaS activa en el sistema.")

        return self.get_response(request)