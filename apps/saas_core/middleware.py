# apps/academias/middleware.py

from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import Http404
from apps.saas_core.models import ConfigPagoGlobalSaaS  # Importamos tu nuevo modelo flexible

class TenantLicensingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Ignoramos las consolas maestras y el Django admin para no bloquearte a ti mismo como SuperAdmin
        if request.path.startswith('/master/') or request.path.startswith('/admin/'):
            return self.get_response(request)

        # 2. Si la petición está dentro del ecosistema de una escuela de baile (Tenant Activo)
        if hasattr(request, 'tenant') and request.tenant:
            try:
                suscripcion = request.tenant.suscripcion_saas
                
                # 🛡️ INTERCEPCIÓN PRO: CONTROL DE BLOQUEO TOTAL EN TIEMPO REAL
                # Evaluamos si la cuenta está marcada como SUSPENDIDA o si ya expiró en fecha (Hora Colombia)
                if suscripcion.esta_bloqueada:
                    # Definimos excepciones de rutas de escape para evitar bloqueos infinitos de navegación (Bucle 302)
                    url_landing_publica = f"/{request.tenant.slug}/"
                    url_logout_seguro = f"/{request.tenant.slug}/logout/"
                    
                    # Si el usuario NO está en la landing page y NO está intentando salir del sistema, le cortamos el paso
                    if request.path != url_landing_publica and 'logout' not in request.path:
                        # Recuperamos la configuración de pago polimórfica (Nequi, Llave, Banco)
                        datos_pago = ConfigPagoGlobalSaaS.objects.first()
                        
                        # Renderizamos directamente la vista de aviso de corte sin dejar pasar la petición a las vistas
                        return render(request, 'academias/bloqueado_pago.html', {
                            'academia': request.tenant,
                            'suscripcion': suscripcion,
                            'datos_pago': datos_pago,
                            'monto_a_pagar': suscripcion.plan.precio_mensual
                        }, status=403) # Enviamos un estado de protección HTTP 403 Forbidden

                # -----------------------------------------------------------------
                # MANTENEMOS TUS CONTROLES MODULARES ORIGINALES (¡EXCELENTE LÓGICA!)
                # -----------------------------------------------------------------

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
                    if not suscripcion.plan.permite_eventos or suscripcion.bloqueo_manual_eventos:
                        messages.error(request, "Acceso restringido al módulo de gestión de eventos.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)
                    
                # 🚫 CONTROL MODULAR TIENDA POS E INVENTARIOS
                if 'tienda' in request.path:
                    if not suscripcion.plan.permite_tienda or suscripcion.bloqueo_manual_tienda:
                        messages.error(request, "El módulo de Tienda e Inventarios no está habilitado en su licencia actual.")
                        return redirect('academias:dashboard', slug_academia=request.tenant.slug)
                    
                    # Filtro Anti-Fraude de tu autoría (Tarjeta de Respaldo)
                    if not request.tenant.tarjeta_respaldo_configurada and not 'configuracion' in request.path:
                        messages.warning(request, "Atención: Debes vincular una tarjeta de respaldo activa en tu Panel de Configuración antes de poder gestionar o aperturar tus Eventos.")

            except Exception:
                # Si ocurre una desalineación de llaves foráneas o datos huérfanos
                if not request.path == f"/{request.tenant.slug}/":
                    raise Http404("La academia no cuenta con una licencia SaaS activa en el sistema.")

        return self.get_response(request)