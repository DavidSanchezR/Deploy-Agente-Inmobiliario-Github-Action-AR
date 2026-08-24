"""
Histórico de conversación persistente en PostgreSQL.
Usa langchain-postgres + psycopg para guardar la conversación por session_id.

Requeridas en .env: DB_USER, DB_PASSWORD, DB_HOST
Opcionales: DB_PORT (5432), DB_NAME (postgres)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
from urllib.parse import quote_plus

from dotenv import load_dotenv, find_dotenv
from langchain_postgres import PostgresChatMessageHistory
import psycopg

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN DE BASE DE DATOS
# ============================================
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")

if not all([DB_USER, DB_PASSWORD, DB_HOST]):
    raise ValueError(
        "❌ Faltan variables de base de datos en .env\n"
        "Requeridas: DB_USER, DB_PASSWORD, DB_HOST"
    )

DATABASE_URL = (
    f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

TABLE_NAME = os.getenv("DB_CHAT_TABLE", "chat_history")

print(f"🔌 Conectando como: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")


# ============================================
# FUNCIONES PÚBLICAS
# ============================================
def crear_tabla_historial() -> None:
    """Crea la tabla de historial en PostgreSQL si no existe."""
    try:
        sync_connection = psycopg.connect(DATABASE_URL)
        PostgresChatMessageHistory.create_tables(sync_connection, TABLE_NAME)
        sync_connection.close()
    except Exception as e:
        print(f"⚠️ Nota sobre tabla: {e}")


def get_session_history(session_id: str) -> PostgresChatMessageHistory:
    """Obtiene/crea el historial de conversación para un session_id."""
    sync_connection = psycopg.connect(DATABASE_URL)
    return PostgresChatMessageHistory(
        TABLE_NAME,
        session_id,
        sync_connection=sync_connection,
    )
