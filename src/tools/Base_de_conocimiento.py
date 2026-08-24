"""
Tool: Base de Conocimiento de Alpha State (RAG con Qdrant).

Consulta las políticas de alquiler, el detalle de los conceptos del boleto, los
requisitos documentales y las FAQ de Alpha State Assessoria Imobiliária.

El par (modelo de embeddings, colección) NO se define acá: viene de
vector_store.py, que es la fuente única. Así la consulta no puede desalinearse
de la ingesta.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys

from langchain_core.tools import tool

# La raíz del proyecto al path: vector_store.py vive un nivel arriba de tools/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vector_store import COLLECTION_NAME, get_vectorstore

# ============================================
# CONFIGURACIÓN
# ============================================
# Documentos a recuperar por consulta.
TOP_K = 5

# El vector store se construye UNA vez al importar el módulo, no por consulta:
# instanciarlo en cada llamada agrega latencia en cada turno del agente.
vectorstore = get_vectorstore()


# ============================================
# FUNCIÓN INTERNA DE BÚSQUEDA
# ============================================
def buscar_en_base_conocimiento_interno(query: str, top_k: int = TOP_K) -> str:
    """
    Búsqueda semántica en la colección de Alpha State.

    Args:
        query: Consulta de búsqueda
        top_k: Número de documentos a retornar

    Returns:
        str: Fragmentos encontrados, formateados para el modelo
    """
    try:
        docs = vectorstore.similarity_search(query, k=top_k)

        if not docs:
            return (
                "No encontré información sobre eso en la base de conocimiento de "
                "Alpha State. No inventes una respuesta: dile al usuario que no "
                "tienes ese dato y ofrécele derivarlo con un asesor."
            )

        contexto = "Información encontrada en la base de conocimiento:\n\n"
        for i, doc in enumerate(docs, 1):
            contexto += f"[{i}]\n{doc.page_content}\n\n"

        return contexto

    except Exception as e:
        return (
            f"Error al consultar la base de conocimiento ({COLLECTION_NAME}): {e}. "
            f"Avísale al usuario que no pudiste verificar la información ahora."
        )


# ============================================
# TOOL EXPORTABLE
# ============================================
@tool
def buscar_alpha_state(consulta: str) -> str:
    """
    Consulta las políticas y procedimientos de Alpha State Assessoria Imobiliária.

    Es la ÚNICA fuente válida para reglas del alquiler. Úsala siempre que el
    locatario pregunte por:
    - Multas por pago atrasado, intereses de demora, boleto vencido
    - Reajuste anual del alquiler y qué índice se aplica
    - Qué significa cada concepto del boleto (alquiler neto, IPTU, agua/SANASA,
      seguro de incendio, gastos bancarios)
    - Cómo se dividen los servicios compartidos entre unidades
    - Documentación y garantías necesarias para alquilar un inmueble
    - Quién paga cada reparación: propietario o locatario
    - Dónde y cómo pagar el boleto

    NO la uses para consultar el importe concreto de un locatario: para eso están
    consultar_total_inquilino y consultar_desglose_inquilino.

    Args:
        consulta: La pregunta o tema a buscar, en lenguaje natural
    """
    print(f"   🔍 Buscando en la base de Alpha State: '{consulta}'")
    return buscar_en_base_conocimiento_interno(consulta)
