# apps/multimedia/utils.py
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials

def subir_video_a_youtube(credentials_dict, file_objeto, titulo, descripcion=""):
    """
    Recibe las credenciales OAuth de la sesión, el archivo binario del video 
    y lo sube directamente a YouTube en modo OCULTO (unlisted).
    """
    credentials = Credentials.from_authorized_user_info(credentials_dict)
    youtube = build('youtube', 'v3', credentials=credentials)

    # Definimos la metadata del video exigida por Google
    body = {
        'snippet': {
            'title': titulo,
            'description': descripcion,
            'tags': ['DistritoSocial', 'ClaseBaile'],
            'categoryId': '22'  # Categoría: Gente y Blogs o Entretenimiento
        },
        'status': {
            'privacyStatus': 'unlisted'  # 🚨 CLAVE: 'unlisted' significa Oculto en YouTube
        }
    }

    # Creamos el flujo de subida desde el objeto en memoria
    media = MediaIoBaseUpload(file_objeto, mimetype='video/*', chunksize=1024*1024, resumable=True)

    # Disparamos la petición a la API
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = request.execute()
    
    # Retornamos el ID único del video asignado por YouTube (Ej: 'dQw4w9WgXcQ')
    return response.get('id')