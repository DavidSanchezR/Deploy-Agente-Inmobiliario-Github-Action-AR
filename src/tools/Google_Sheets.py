"""
Tool: Consulta del boleto mensual de los locatarios en Google Sheets (SOLO LECTURA)
Lee la hoja de cálculo de Alpha State con los importes del mes usando
una cuenta de servicio de Google Cloud.

Expone dos tools al agente:
- consultar_total_inquilino: monto total a pagar de un inquilino en el mes actual
- consultar_desglose_inquilino: detalle de qué incluye su boleto (alquiler, IPTU, agua, etc.)

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import re
import json
import unicodedata
from typing import Optional

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread
from google.oauth2.service_account import Credentials

load_dotenv(find_dotenv())

# ============================================
# CONFIGURACIÓN
# ============================================
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEETS_WORKSHEET = os.getenv("GOOGLE_SHEETS_WORKSHEET", "Rio Sul")
GOOGLE_SHEETS_HEADER_ROW = int(os.getenv("GOOGLE_SHEETS_HEADER_ROW", "3"))
# Fila opcional con agrupaciones por encima de los headers (ej. "Consumo de Agua",
# "SubTotal", "Total"). Si una celda de header está vacía, se usa el valor de
# esta fila. Por defecto, la fila inmediatamente anterior a HEADER_ROW.
GOOGLE_SHEETS_GROUP_ROW = int(
    os.getenv("GOOGLE_SHEETS_GROUP_ROW", str(max(1, GOOGLE_SHEETS_HEADER_ROW - 1)))
)
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "credentials/service-account.json",
)

# Scope de SOLO LECTURA
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

if not GOOGLE_SHEET_ID:
    raise ValueError(
        "❌ Falta variable GOOGLE_SHEET_ID en .env"
    )


# ============================================
# CLIENTE GSPREAD (lazy + cache simple)
# ============================================
_worksheet = None


def _resolve_credentials_path(path: str) -> str:
    """Si la ruta es relativa, la resuelve contra el directorio del proyecto."""
    if os.path.isabs(path):
        return path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, path)


def _get_worksheet():
    """Conecta a Google Sheets de forma lazy y devuelve el worksheet."""
    global _worksheet

    if _worksheet is not None:
        print("   🔸 [sheets] _get_worksheet: usando worksheet cacheado (ya conectado antes)", flush=True)
        return _worksheet

    print("   🔸 [sheets] _get_worksheet: sin caché, iniciando conexión...", flush=True)
    credentials_value = GOOGLE_APPLICATION_CREDENTIALS.strip()

    # Cloud Run / Secret Manager:
    # GOOGLE_APPLICATION_CREDENTIALS contiene directamente el JSON.
    if credentials_value.startswith("{"):
        print("   🔸 [sheets] Credencial detectada como JSON inline (variable de entorno / secreto)", flush=True)
        try:
            credentials_info = json.loads(credentials_value)
        except json.JSONDecodeError as e:
            print(f"   ❌ [sheets] El JSON de GOOGLE_APPLICATION_CREDENTIALS es inválido: {e}", flush=True)
            raise ValueError(
                "El secreto GOOGLE_APPLICATION_CREDENTIALS no contiene un JSON válido."
            ) from e

        try:
            creds = Credentials.from_service_account_info(
                credentials_info,
                scopes=SCOPES,
            )
            print(f"   🔸 [sheets] Credenciales cargadas OK para: "
                  f"{credentials_info.get('client_email', '¿desconocido?')}", flush=True)
        except Exception as e:
            print(f"   ❌ [sheets] Error creando Credentials.from_service_account_info: "
                  f"{type(e).__name__}: {e}", flush=True)
            raise

    # Entorno local:
    # GOOGLE_APPLICATION_CREDENTIALS contiene una ruta al JSON.
    else:
        creds_path = _resolve_credentials_path(credentials_value)
        print(f"   🔸 [sheets] Credencial detectada como ruta de archivo: '{creds_path}'", flush=True)

        if not os.path.isfile(creds_path):
            print(f"   ❌ [sheets] No se encontró el archivo de credenciales en '{creds_path}'", flush=True)
            raise FileNotFoundError(
                f"No se encontró el JSON de la cuenta de servicio en '{creds_path}'."
            )

        try:
            creds = Credentials.from_service_account_file(
                creds_path,
                scopes=SCOPES,
            )
            print("   🔸 [sheets] Credenciales cargadas OK desde archivo", flush=True)
        except Exception as e:
            print(f"   ❌ [sheets] Error creando Credentials.from_service_account_file: "
                  f"{type(e).__name__}: {e}", flush=True)
            raise

    try:
        client = gspread.authorize(creds)
        print("   🔸 [sheets] gspread.authorize() OK", flush=True)
    except Exception as e:
        print(f"   ❌ [sheets] Error en gspread.authorize(): {type(e).__name__}: {e}", flush=True)
        raise

    try:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        print(f"   🔸 [sheets] open_by_key('{GOOGLE_SHEET_ID}') OK -> spreadsheet '{sheet.title}'", flush=True)
    except Exception as e:
        print(f"   ❌ [sheets] Error en open_by_key('{GOOGLE_SHEET_ID}'): "
              f"{type(e).__name__}: {e}", flush=True)
        raise

    try:
        _worksheet = sheet.worksheet(GOOGLE_SHEETS_WORKSHEET)
        print(f"   🔸 [sheets] worksheet('{GOOGLE_SHEETS_WORKSHEET}') OK", flush=True)
    except Exception as e:
        print(f"   ❌ [sheets] Error en worksheet('{GOOGLE_SHEETS_WORKSHEET}'): "
              f"{type(e).__name__}: {e}", flush=True)
        raise

    return _worksheet


# ============================================
# UTILIDADES
# ============================================
def _normalize(text) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin espacios extra."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _dedup_headers(headers: list) -> list:
    """Renombra duplicados con sufijo numérico (Total → Total, Total_2, Total_3)."""
    counts = {}
    out = []
    for h in headers:
        h = (h or "").strip() or "Columna"
        if h in counts:
            counts[h] += 1
            out.append(f"{h}_{counts[h]}")
        else:
            counts[h] = 1
            out.append(h)
    return out


def _parse_amount(value) -> Optional[float]:
    """Convierte un valor tipo '1,234.56', 'S/ 50.00', '$50' a float. None si no se puede."""
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    s = re.sub(r"[A-Za-z$/\s]", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Heurística: si hay 2 dígitos tras la coma, es decimal
        partes = s.split(",")
        if len(partes[-1]) == 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _merge_headers_con_grupos(group_row: list, header_row: list) -> list:
    """Combina la fila de agrupaciones con la fila de headers:
    - Si el header (fila 2) tiene valor, lo usa tal cual.
    - Si el header está vacío, usa el valor más reciente no vacío de la fila de grupos.
    """
    merged = []
    current_group = ""
    for i in range(max(len(group_row), len(header_row))):
        grp = (group_row[i].strip() if i < len(group_row) else "")
        hdr = (header_row[i].strip() if i < len(header_row) else "")
        if grp:
            current_group = grp
        merged.append(hdr or current_group or "Columna")
    return merged


def _cargar_datos():
    """Lee la hoja y devuelve (headers, data_rows)."""
    print("   🔸 [sheets] _cargar_datos: obteniendo worksheet...", flush=True)
    ws = _get_worksheet()

    try:
        all_values = ws.get_all_values()
        print(f"   🔸 [sheets] get_all_values() OK -> {len(all_values)} fila(s) leída(s)", flush=True)
    except Exception as e:
        print(f"   ❌ [sheets] Error en get_all_values(): {type(e).__name__}: {e}", flush=True)
        raise

    header_idx = GOOGLE_SHEETS_HEADER_ROW - 1
    group_idx = GOOGLE_SHEETS_GROUP_ROW - 1
    if header_idx >= len(all_values):
        print(f"   ❌ [sheets] La hoja solo tiene {len(all_values)} fila(s), "
              f"no alcanza la fila de encabezado {GOOGLE_SHEETS_HEADER_ROW}", flush=True)
        raise ValueError(
            f"La hoja no tiene fila {GOOGLE_SHEETS_HEADER_ROW} para usar como encabezado."
        )
    header_row = all_values[header_idx]
    if 0 <= group_idx < len(all_values) and group_idx != header_idx:
        headers = _merge_headers_con_grupos(all_values[group_idx], header_row)
    else:
        headers = [(h or "").strip() or "Columna" for h in header_row]
    headers = _dedup_headers(headers)
    data_rows = [r for r in all_values[header_idx + 1:] if any(c.strip() for c in r)]
    print(f"   🔸 [sheets] Headers parseados ({len(headers)}): {headers}", flush=True)
    print(f"   🔸 [sheets] Filas de datos con contenido: {len(data_rows)}", flush=True)
    return headers, data_rows


def _columnas_identificadoras(headers: list) -> tuple:
    """Devuelve (idx_nombre, idx_depto) buscando por palabras clave en los headers."""
    idx_nombre = None
    idx_depto = None
    for i, h in enumerate(headers):
        h_norm = _normalize(h)
        if idx_nombre is None and any(k in h_norm for k in ("responsable", "inquilino", "nombre")):
            idx_nombre = i
        if idx_depto is None and any(k in h_norm for k in ("depart", "depto", "unidad", "bloque")):
            idx_depto = i
    return idx_nombre, idx_depto


def _buscar_fila_inquilino(rows: list, headers: list, identificador: str) -> Optional[dict]:
    """Busca la fila de un locatario por nombre (parcial) o identificador de unidad."""
    ident_norm = _normalize(identificador)
    if not ident_norm:
        print("   ⚠️ [sheets] _buscar_fila_inquilino: identificador vacío tras normalizar", flush=True)
        return None

    idx_nombre, idx_depto = _columnas_identificadoras(headers)
    print(f"   🔸 [sheets] _buscar_fila_inquilino: identificador='{ident_norm}' | "
          f"idx_nombre={idx_nombre} | idx_depto={idx_depto} | {len(rows)} fila(s) a revisar", flush=True)
    es_numero = bool(re.fullmatch(r"\d+", ident_norm))

    # Pase 1: si es número, priorizar coincidencia exacta por depto
    if es_numero and idx_depto is not None:
        for row in rows:
            if idx_depto < len(row) and _normalize(row[idx_depto]) == ident_norm:
                print(f"   ✅ [sheets] Match en Pase 1 (depto exacto): fila -> {row}", flush=True)
                return dict(zip(headers, row))

    # Pase 2: coincidencia parcial por nombre
    if idx_nombre is not None:
        for row in rows:
            if idx_nombre < len(row):
                nombre = _normalize(row[idx_nombre])
                if nombre and ident_norm in nombre:
                    print(f"   ✅ [sheets] Match en Pase 2 (nombre parcial): fila -> {row}", flush=True)
                    return dict(zip(headers, row))

    # Pase 3: coincidencia parcial por depto (para casos como "depto 301" → "301")
    if idx_depto is not None:
        for row in rows:
            if idx_depto < len(row):
                depto = _normalize(row[idx_depto])
                if depto and (depto == ident_norm or ident_norm in depto):
                    print(f"   ✅ [sheets] Match en Pase 3 (depto parcial): fila -> {row}", flush=True)
                    return dict(zip(headers, row))

    print(f"   ⚠️ [sheets] _buscar_fila_inquilino: SIN coincidencias para '{ident_norm}' "
          f"en {len(rows)} fila(s)", flush=True)
    return None


def _identificar_columna_total(headers: list) -> Optional[str]:
    """Encuentra la columna del Total general (no totales parciales)."""
    # Prioridad 1: coincidencia exacta "total"
    for h in reversed(headers):
        if _normalize(h) == "total":
            return h
    # Prioridad 2: última columna que contenga "total" pero no "sub"
    for h in reversed(headers):
        h_norm = _normalize(h)
        if "total" in h_norm and "sub" not in h_norm:
            return h
    return None


def _extraer_identidad(fila: dict, headers: list) -> tuple:
    """Devuelve (nombre, depto) extraídos de la fila."""
    idx_nombre, idx_depto = _columnas_identificadoras(headers)
    nombre = fila.get(headers[idx_nombre], "") if idx_nombre is not None else ""
    depto = fila.get(headers[idx_depto], "") if idx_depto is not None else ""
    return nombre, depto


# ============================================
# TOOLS EXPORTABLES
# ============================================
@tool
def consultar_total_inquilino(identificador: str) -> str:
    """
    Consulta el monto TOTAL del boleto de un locatario en el mes actual.

    Úsala cuando el locatario pregunte:
    - "¿Cuánto debo pagar este mes?"
    - "¿Cuánto es mi alquiler?"
    - "¿Cuánto vino el boleto?"

    NO la uses para explicar reglas de multas, intereses o reajuste: para eso
    está buscar_alpha_state.

    Args:
        identificador: Nombre completo o parcial del locatario, o identificador
                       de su unidad. Ejemplos: "Juan Pérez", "Juan", "301".
    """
    print(f"   🏢 Consultando total para: '{identificador}'")
    try:
        headers, rows = _cargar_datos()
        fila = _buscar_fila_inquilino(rows, headers, identificador)
        if not fila:
            return (
                f"No encontré un locatario que coincida con '{identificador}'. "
                f"Pídele al usuario que confirme su nombre completo o el "
                f"identificador de su unidad."
            )

        nombre, depto = _extraer_identidad(fila, headers)
        col_total = _identificar_columna_total(headers)
        total = fila.get(col_total) if col_total else None

        partes = ["💰 Boleto del mes:"]
        if nombre:
            partes.append(f"- Inquilino: {nombre}")
        if depto:
            partes.append(f"- Departamento: {depto}")
        if total:
            partes.append(f"- Total a pagar: {total}")
        else:
            partes.append(
                "- No pude identificar la columna de Total. "
                "Usa consultar_desglose_inquilino para ver el detalle."
            )
        return "\n".join(partes)
    except Exception as e:
        print(f"❌ ERROR GOOGLE SHEETS: {type(e).__name__}: {e}", flush=True)
        return f"Error al consultar Google Sheets: {str(e)}"


@tool
def consultar_desglose_inquilino(identificador: str) -> str:
    """
    Devuelve el DESGLOSE COMPLETO por concepto del boleto de un locatario:
    alquiler neto, IPTU, agua/saneamiento, seguro de incendio, gastos
    bancarios y demás conceptos del contrato.

    Úsala cuando el locatario pregunte:
    - "¿Por qué vino tan alto?"
    - "¿Qué incluye el boleto?"
    - "¿Cuánto es el IPTU / el agua / el seguro?"
    - "Dame el detalle"

    Args:
        identificador: Nombre completo o parcial del locatario, o identificador
                       de su unidad. Ejemplos: "Juan Pérez", "Juan", "301".
    """
    print(f"   🏢 Consultando desglose para: '{identificador}'")
    try:
        headers, rows = _cargar_datos()
        fila = _buscar_fila_inquilino(rows, headers, identificador)
        if not fila:
            return (
                f"No encontré un locatario que coincida con '{identificador}'. "
                f"Pídele al usuario que confirme su nombre completo o el "
                f"identificador de su unidad."
            )

        nombre, depto = _extraer_identidad(fila, headers)

        # Columnas a omitir en el desglose (identificadores y metadatos)
        skip_terms = (
            "responsable", "inquilino", "nombre", "depart", "depto",
            "unidad", "bloque", "participacion",
        )

        partes = ["📋 Desglose del boleto:"]
        if nombre:
            partes.append(f"- Inquilino: {nombre}")
        if depto:
            partes.append(f"- Departamento: {depto}")
        partes.append("")
        partes.append("Conceptos:")

        mostrados = 0
        for col, val in fila.items():
            col_norm = _normalize(col)
            if any(t in col_norm for t in skip_terms):
                continue
            monto = _parse_amount(val)
            if monto is None or monto == 0:
                continue
            partes.append(f"  • {col}: {val}")
            mostrados += 1

        if mostrados == 0:
            partes.append(
                "  (No hay conceptos con monto registrado para este inquilino)"
            )

        return "\n".join(partes)
    except Exception as e:
        print(f"❌ ERROR GOOGLE SHEETS: {type(e).__name__}: {e}", flush=True)
        return f"Error al consultar Google Sheets: {str(e)}"
