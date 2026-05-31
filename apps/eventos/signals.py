# apps/eventos/signals.py
import qrcode
import os
import logging
from io import BytesIO
from django.core.files import File
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from django.apps import apps
from .models import EntradaQR

# Herramientas de Pillow
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

@receiver(post_save, sender=EntradaQR)
def generar_codigo_qr_boleta(sender, instance, created, **kwargs):
    """
    Signal Indestructible: Carga local, busca en fuentes de Windows/Linux del S.O.
    y si todo falla, descarga la fuente vectorial directo de Google Fonts a la RAM.
    """
    if created and not instance.imagen_qr:
        recibo = instance.recibo
        evento = recibo.evento
        academia = evento.academia

        # 1. Configurar Lienzo Maestro en Alta Resolución (700x1050)
        ancho_tarjeta = 700
        alto_tarjeta = 1050  
        tarjeta = Image.new('RGB', (ancho_tarjeta, alto_tarjeta), color='white')
        canvas = ImageDraw.Draw(tarjeta)

        # Borde exterior estético
        canvas.rectangle([(20, 20), (ancho_tarjeta - 20, alto_tarjeta - 20)], outline="#ced4da", width=4)

        # ----------------------------------------------------
        # 🚀 CAZADOR ULTRA-BLINDADO DE FUENTES (MEMORIA + S.O.)
        # ----------------------------------------------------
        fuente_final = None
        
        # Intento 1: Ruta explícita en tu app de Django
        try:
            ruta_app = apps.get_app_config('eventos').path
            fuente_local = os.path.join(ruta_app, "Roboto-Bold.ttf")
            if os.path.exists(fuente_local):
                fuente_final = fuente_local
        except Exception:
            pass

        # Intento 2: Si estás en Windows local, Pillow sabe buscar por nombre en C:\Windows\Fonts
        if not fuente_final:
            for nombre_win in ["arialbd.ttf", "arial.ttf", "calibrib.ttf", "segoeuib.ttf"]:
                try:
                    ImageFont.truetype(nombre_win, 10)
                    fuente_final = nombre_win
                    print(f"--- [QR_SIGNAL] Detectada fuente nativa de Windows: {nombre_win} ---")
                    break
                except Exception:
                    continue

        # Intento 3: Si estás en producción en PythonAnywhere (Linux Ubuntu)
        if not fuente_final:
            paths_linux = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ]
            for path in paths_linux:
                if os.path.exists(path):
                    fuente_final = path
                    break

        # Intento 4 (El Salvador de Emergencias): Descarga directa a RAM desde Google Fonts
        if not fuente_final:
            print("--- [QR_SIGNAL] Alerta: No hay fuentes físicas. Descargando de Google Fonts... ---")
            try:
                import requests
                # URL directa al TTF crudo de Montserrat Black o Roboto Bold en los servidores de Google
                url_fuente = "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf"
                respuesta = requests.get(url_fuente, timeout=3)
                if respuesta.status_code == 200:
                    # Guardamos el archivo binario directamente en un BytesIO de memoria volatil
                    fuente_en_memoria = BytesIO(respuesta.content)
                    print("--- [QR_SIGNAL] ¡Fuente descargada con éxito a la RAM! ---")
            except Exception as e:
                logger.error(f"[QR_SIGNAL] Falló la descarga de emergencia: {str(e)}")
                fuente_en_memoria = None
        else:
            fuente_en_memoria = None

        # ----------------------------------------------------
        # 🎭 ASIGNACIÓN ASISTIDA POR TIPO DE INYECCIÓN
        # ----------------------------------------------------
        def obtener_instancia_fuente(size):
            """Helper para instanciar la fuente desde disco o desde el buffer de memoria"""
            try:
                if fuente_en_memoria:
                    # Clonamos el puntero del BytesIO para que pueda leerse múltiples veces
                    fuente_en_memoria.seek(0)
                    return ImageFont.truetype(fuente_en_memoria, size)
                elif fuente_final:
                    return ImageFont.truetype(fuente_final, size)
                return ImageFont.load_default()
            except Exception:
                return ImageFont.load_default()

        # Generamos las fuentes escalables reales
        fuente_academia = obtener_instancia_fuente(26)
        fuente_titulo   = obtener_instancia_fuente(44)
        fuente_badge    = obtener_instancia_fuente(22)
        fuente_subtitulo= obtener_instancia_fuente(20)
        fuente_comprador= obtener_instancia_fuente(40)
        fuente_footer_id= obtener_instancia_fuente(16)
        fuente_footer_txt= obtener_instancia_fuente(22)

        # Si caímos al default por una catástrofe total, avisamos
        if isinstance(fuente_titulo, ImageFont.ImageFont):
            pass # Todo perfecto, es una fuente TrueType real
        else:
            logger.critical("[QR_SIGNAL] No se pudo mapear ninguna fuente tipográfica escalable.")

        # ----------------------------------------------------
        # 2. Renderizar Textos Centrados Nativos
        # ----------------------------------------------------
        # ACADEMIA
        canvas.text((ancho_tarjeta / 2, 80), academia.nombre.upper(), fill="#6c757d", font=fuente_academia, anchor="mm")

        # NOMBRE DEL EVENTO
        canvas.text((ancho_tarjeta / 2, 145), evento.nombre, fill="#212529", font=fuente_titulo, anchor="mm")

        # BADGE DE LA BOLETA
        total_boletas = recibo.cantidad_entradas
        lista_boletas = list(recibo.boletas_qr.all().order_by('id'))
        indice_actual = lista_boletas.index(instance) + 1 if instance in lista_boletas else 1
        
        texto_badge = f"BOLETA {indice_actual} DE {total_boletas}"
        
        bw, bh = 280, 50
        bx1, by1 = (ancho_tarjeta - bw) / 2, 200
        
        canvas.rounded_rectangle([bx1, by1, bx1 + bw, by1 + bh], radius=8, fill="#212529")
        canvas.text((ancho_tarjeta / 2, by1 + (bh / 2)), texto_badge, fill="#ffc107", font=fuente_badge, anchor="mm")

        # TITULAR DE LA ENTRADA
        canvas.text((ancho_tarjeta / 2, 305), "TITULAR DE LA ENTRADA", fill="#6c757d", font=fuente_subtitulo, anchor="mm")
        
        # NOMBRE DEL COMPRADOR
        canvas.text((ancho_tarjeta / 2, 365), recibo.comprador_nombre, fill="#212529", font=fuente_comprador, anchor="mm")

        # ----------------------------------------------------
        # 3. Fabricar e Integrar el Código QR Centrado
        # ----------------------------------------------------
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=12,
            border=0,
        )
        qr.add_data(str(instance.codigo_unico))
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        
        tamano_qr = 380 
        qr_img = qr_img.resize((tamano_qr, tamano_qr), Image.Resampling.LANCZOS)

        pos_x = int((ancho_tarjeta - tamano_qr) / 2)
        pos_y = 475  
        tarjeta.paste(qr_img, (pos_x, pos_y))
        
        canvas.rounded_rectangle([pos_x - 20, pos_y - 20, pos_x + tamano_qr + 20, pos_y + tamano_qr + 20], outline="#e9ecef", width=3, radius=16)

        # ----------------------------------------------------
        # 4. Sección Inferior (Footer)
        # ----------------------------------------------------
        linea_y = 940
        canvas.line([(40, linea_y), (ancho_tarjeta - 40, linea_y)], fill="#e9ecef", width=2)

        canvas.text((ancho_tarjeta / 2, linea_y + 30), f"ID: {str(instance.codigo_unico)}", fill="#6c757d", font=fuente_footer_id, anchor="mm")
        canvas.text((ancho_tarjeta / 2, linea_y + 65), "Entrada válida para un solo ingreso", fill="#495057", font=fuente_footer_txt, anchor="mm")

        # ----------------------------------------------------
        # 5. Volcar y guardar el archivo final
        # ----------------------------------------------------
        blob = BytesIO()
        tarjeta.save(blob, 'PNG', quality=100)
        nombre_archivo = f"Pase-{slugify(evento.nombre)}-{instance.codigo_unico}.png"
        
        instance.imagen_qr.save(nombre_archivo, File(blob), save=False)
        instance.save(update_fields=['imagen_qr'])