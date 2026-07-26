from django import template

register = template.Library()

@register.filter(name='get_item')
def get_item(dictionary, key):
    """
    Filtro personalizado para Django: Permite buscar una clave dinámica 
    dentro de un diccionario directamente desde una plantilla HTML.
    Ejemplo: {{ mi_diccionario|get_item:mi_variable_clave }}
    """
    if dictionary and key:
        return dictionary.get(key)
    return None