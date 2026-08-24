"""
Agente IA Completo: Base de Conocimiento + Internet + Histórico
- Tool 1: Base de Conocimiento de Alpha State (RAG con Qdrant)
- Tool 2: Búsqueda en Internet (Tavily)
- Histórico: Guarda conversaciones en PostgreSQL
- Config del modelo: model_config/model_config.yaml
- System prompt: prompt/prompt.yaml

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Agregar el directorio actual al path para importar tools (portable para despliegue)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# ============================================
# 0. CARGA DE CONFIGURACIÓN (YAML)
# ============================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_CONFIG_PATH = os.path.join(BASE_DIR, "model_config", "model_config.yaml")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt", "prompt.yaml")


def _cargar_yaml(ruta: str) -> dict:
    """Lee un archivo YAML de configuración y lo devuelve como dict."""
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


model_config = _cargar_yaml(MODEL_CONFIG_PATH)
prompt_config = _cargar_yaml(PROMPT_PATH)

# Importar tools desde la carpeta tools/
from tools.Base_de_conocimiento import buscar_alpha_state
from tools.Busqueda_internet import buscar_internet
from tools.Hora_y_fecha import obtener_fecha_hora
from tools.Google_Sheets import (
    consultar_total_inquilino,
    consultar_desglose_inquilino,
)

# Histórico de conversación (PostgreSQL)
from conversation_history import crear_tabla_historial, get_session_history

# ============================================
# 2. LISTA DE TOOLS DISPONIBLES
# ============================================
tools = [
    buscar_alpha_state,                # Base de conocimiento Alpha State (RAG/Qdrant)
    buscar_internet,                # Búsqueda en internet (Tavily)
    obtener_fecha_hora,             # Fecha y hora actual por zona horaria
    consultar_total_inquilino,      # Total mensual de un inquilino (Google Sheets)
    consultar_desglose_inquilino,   # Desglose de la cuota de un inquilino (Google Sheets)
]

# ============================================
# 3. CONFIGURACIÓN DEL MODELO CON TOOLS
# ============================================
# Parámetros del LLM desde model_config/model_config.yaml
_llm_cfg = model_config["llm"]

chat = init_chat_model(
    _llm_cfg["model"],
    model_provider=_llm_cfg["provider"],
    temperature=_llm_cfg["temperature"],
)
chat_con_tools = chat.bind_tools(tools)

# ============================================
# 4. PROMPT DEL AGENTE + CONTEXTO FECHA/HORA
# ============================================
# La zona horaria puede venir del .env; si no, del bloque `agent` de model_config/model_config.yaml
AGENT_TIMEZONE = os.getenv(
    "AGENT_TIMEZONE",
    model_config.get("agent", {}).get("timezone", "America/Lima"),
)

# Plantilla del system prompt (prompt/prompt.yaml). Los placeholders se inyectan por turno.
SYSTEM_PROMPT_TEMPLATE = prompt_config["system_prompt"]


def _contexto_fecha_hora() -> str:
    """Fecha y hora actual para inyectar en el system prompt (cada turno)."""
    try:
        tz = ZoneInfo(AGENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo("America/Lima")
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" (zona {AGENT_TIMEZONE})"


def _render_system_prompt() -> str:
    """Renderiza el system prompt reemplazando los placeholders de prompt/prompt.yaml."""
    return SYSTEM_PROMPT_TEMPLATE.replace("{fecha_hora_actual}", _contexto_fecha_hora())


# ============================================
# 5. INICIALIZAR HISTORIAL (PostgreSQL)
# ============================================
# crear_tabla_historial y get_session_history se importan desde conversation_history/
crear_tabla_historial()

# ============================================
# 6. FUNCIÓN DE CHAT CON AGENTE + TOOLS
# ============================================
def chat_con_agente(mensaje_usuario: str, session_id: str) -> str:
    """
    Ejecuta el agente con tools y memoria.
    El agente decide si usar herramientas o responder directamente.
    """
    print(f"🟦 [agent] INICIO | session={session_id} | mensaje='{mensaje_usuario[:120]}'", flush=True)

    # Obtener historial
    try:
        history = get_session_history(session_id)
        mensajes_previos = history.messages
        print(f"🟦 [agent] Historial cargado: {len(mensajes_previos)} mensaje(s) previo(s)", flush=True)
    except Exception as e:
        print(f"❌ [agent] ERROR al cargar historial (PostgreSQL): {type(e).__name__}: {e}", flush=True)
        raise

    # Construir mensajes para el modelo (inyectamos fecha/hora actual en cada turno)
    messages = [{"role": "system", "content": _render_system_prompt()}]

    # Agregar historial
    for msg in mensajes_previos:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})

    # Agregar mensaje actual
    messages.append({"role": "user", "content": mensaje_usuario})

    # Invocar modelo con tools
    print(f"🟦 [agent] Invocando modelo (1ra llamada) | {len(messages)} mensajes | "
          f"{len(tools)} tools disponibles: {[t.name for t in tools]}", flush=True)
    try:
        response = chat_con_tools.invoke(messages)
    except Exception as e:
        print(f"❌ [agent] ERROR en la 1ra llamada al modelo: {type(e).__name__}: {e}", flush=True)
        raise

    # Procesar tool calls si existen
    if response.tool_calls:
        print(f"🟩 [agent] El modelo SÍ solicitó tool(s): "
              f"{[tc['name'] for tc in response.tool_calls]}", flush=True)

        # Ejecutar cada tool
        tool_results = []
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"   ➡️ [agent] Ejecutando tool '{tool_name}' con args={tool_args}", flush=True)

            # Buscar y ejecutar la tool
            encontrada = False
            for t in tools:
                if t.name == tool_name:
                    encontrada = True
                    try:
                        result = t.invoke(tool_args)
                        print(f"   ✅ [agent] Tool '{tool_name}' OK -> {len(str(result))} chars devueltos", flush=True)
                    except Exception as e:
                        print(f"   ❌ [agent] ERROR ejecutando tool '{tool_name}': "
                              f"{type(e).__name__}: {e}", flush=True)
                        result = f"Error ejecutando la herramienta '{tool_name}': {e}"
                    tool_results.append({
                        "tool_call_id": tool_call["id"],
                        "result": result
                    })
                    break
            if not encontrada:
                print(f"   ⚠️ [agent] El modelo pidió la tool '{tool_name}' pero NO está "
                      f"registrada en `tools` (revisa la lista en agent.py)", flush=True)
                tool_results.append({
                    "tool_call_id": tool_call["id"],
                    "result": f"Error: la herramienta '{tool_name}' no está disponible."
                })

        # Agregar respuesta del modelo con tool calls y resultados
        messages.append(response)
        for tr in tool_results:
            messages.append(ToolMessage(
                content=tr["result"],
                tool_call_id=tr["tool_call_id"]
            ))

        # Segunda llamada para obtener respuesta final
        print(f"🟦 [agent] Invocando modelo (2da llamada) con {len(tool_results)} resultado(s) de tool", flush=True)
        try:
            final_response = chat_con_tools.invoke(messages)
        except Exception as e:
            print(f"❌ [agent] ERROR en la 2da llamada al modelo: {type(e).__name__}: {e}", flush=True)
            raise
        respuesta_final = final_response.content
    else:
        print("🟨 [agent] El modelo NO solicitó ninguna tool (ni Sheets, ni RAG, ni Internet). "
              "Responde directo con lo que ya sabe.", flush=True)
        # Sin tool calls, respuesta directa
        respuesta_final = response.content

    print(f"🟦 [agent] Respuesta final ({len(respuesta_final or '')} chars): "
          f"'{str(respuesta_final)[:200]}'", flush=True)

    # Guardar en historial
    try:
        history.add_user_message(mensaje_usuario)
        history.add_ai_message(respuesta_final)
        print("🟦 [agent] Historial guardado OK", flush=True)
    except Exception as e:
        print(f"❌ [agent] ERROR al guardar historial (PostgreSQL): {type(e).__name__}: {e}", flush=True)
        raise

    return respuesta_final


# ============================================
# 7. LOOP DE CONVERSACIÓN
# ============================================
def main():
    print("=" * 60)
    print("🤖 Agente Alpha State (Sheets + RAG + Internet + Memoria)")
    print("=" * 60)
    print("🔧 Tools disponibles:")
    for t in tools:
        print(f"   - {t.name}")
    print("💾 Historial: PostgreSQL")
    
    # Menú de sesión
    print("\nOpciones de sesión:")
    print("  1. Nueva conversación")
    print("  2. Continuar sesión existente (pegar UUID)")
    
    opcion = input("\nElige (1/2): ").strip()
    
    if opcion == "2":
        session_id = input("Pega el UUID de la sesión: ").strip()
        try:
            uuid.UUID(session_id)
        except ValueError:
            print("⚠️ UUID inválido. Creando nueva sesión...")
            session_id = str(uuid.uuid4())
    else:
        session_id = str(uuid.uuid4())
    
    print(f"\n📝 Session ID: {session_id}")
    print("   (Guarda este ID para continuar después)")
    print("✅ El agente puede consultar Google Sheets, la base de Alpha State e INTERNET")
    print("Escribe 'salir' para volver al menú.\n")
    
    while True:
        usuario = input("Tú: ").strip()
        
        if usuario.lower() in ['salir', 'exit', 'quit']:
            print(f"\n💾 Tu sesión está guardada.")
            print(f"   UUID: {session_id}")
            print("👋 ¡Hasta luego!")
            break
        
        if not usuario:
            continue
        
        try:
            respuesta = chat_con_agente(usuario, session_id)
            print(f"\n🤖 DataBot: {respuesta}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    main()
