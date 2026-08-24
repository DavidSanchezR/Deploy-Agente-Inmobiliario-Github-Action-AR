"""
Tool: Búsqueda en Internet (Tavily)
Permite buscar información actualizada en internet.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE TAVILY
# ============================================
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not TAVILY_API_KEY:
    raise ValueError(
        "❌ Falta TAVILY_API_KEY en .env\n"
        "Obtén tu API key gratis en: https://tavily.com"
    )

# Usar la nueva API de langchain-tavily
try:
    from langchain_tavily import TavilySearch
    tavily_search = TavilySearch(max_results=5)
except ImportError:
    # Fallback a la versión antigua si no está instalada
    from langchain_community.tools.tavily_search import TavilySearchResults
    tavily_search = TavilySearchResults(max_results=5)


# ============================================
# TOOL EXPORTABLE
# ============================================
@tool
def buscar_internet(consulta: str) -> str:
    """
    Busca información actualizada en internet usando Tavily.
    Usa esta herramienta cuando el usuario pregunte sobre:
    - Eventos actuales o noticias recientes
    - Información que cambia frecuentemente
    - Datos ajenos a Alpha State y al contrato de alquiler
    - Cualquier tema que requiera información actualizada de internet
    
    NO uses esta herramienta para:
    - Políticas o procedimientos de Alpha State (usa buscar_alpha_state)
    - Importes del boleto de un locatario (usa las tools de Google Sheets)
    - Saludos o conversación general
    
    Args:
        consulta: La pregunta o tema a buscar en internet
    """
    print(f"   🌐 Buscando en internet: '{consulta}'")
    
    try:
        # Ejecutar búsqueda
        resultados = tavily_search.invoke(consulta)
        
        if not resultados:
            return "No encontré información relevante en internet."
        
        # Formatear resultados
        respuesta = "Información encontrada en internet:\n\n"
        
        # Manejar diferentes formatos de respuesta
        if isinstance(resultados, list):
            for i, resultado in enumerate(resultados, 1):
                if isinstance(resultado, dict):
                    titulo = resultado.get("title", "Sin título")
                    contenido = resultado.get("content", "")
                    url = resultado.get("url", "")
                else:
                    titulo = f"Resultado {i}"
                    contenido = str(resultado)
                    url = ""
                
                respuesta += f"[{i}] {titulo}\n"
                respuesta += f"{contenido[:500]}...\n" if len(contenido) > 500 else f"{contenido}\n"
                if url:
                    respuesta += f"Fuente: {url}\n"
                respuesta += "\n"
        else:
            respuesta += str(resultados)
        
        return respuesta
        
    except Exception as e:
        return f"Error al buscar en internet: {str(e)}"
