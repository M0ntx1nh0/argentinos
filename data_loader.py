"""
data_loader.py
Lee y limpia los CSVs de Hudl Titan y devuelve un DataFrame
con una fila por (partido, nivel, tramo).
"""

import io
import os
import re

import pandas as pd
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

COL_MAP = {
    "Partidos": "tramo",
    "PJ": "pj",
    "G": "goles",
    "A": "asistencias",
    "S": "tiros",
    "L/P": "lp",
    "SOT": "tiros_puerta",
    "%LaP": "pct_eficacia",
    "CE": "centros",
    "SE": "jugadas_set",
    "F": "faltas",
    "PL": "pl",
    "GE": "goles_enc",
    "Pa0": "pa0",
    "Paradas": "paradas",
    "TAP": "tap",
    "MEJORES": "mejor_posesion",
    "P%": "pct_posesion",
    "NºP": "num_posesiones",
    "TAtc": "tatc",
    "P/G": "pg",
    "P/S": "ps",
    "TP/G": "tpg",
    "TP/L": "tpl",
    "CP": "pases_total",
    "SJ": "pases_ok",
    "PI": "pases_perdidos",
    "%PC": "pct_pases",
    "CPT": "cadenas_total",
    "3-5 CP": "cadenas_3_5",
    "6+ CP": "cadenas_6mas",
    "Prom CP": "cadenas_prom",
    "CPML": "cadena_max",
    "IP Atq": "atq_intentados",
    "PC Atq": "atq_completados",
    "PI Atq": "atq_perdidos",
    "%PC Atq": "pct_pases_atq",
    "IP Mitad": "mid_intentados",
    "PC Mitad": "mid_completados",
    "PI Mitad": "mid_perdidos",
    "%PC Mitad": "pct_pases_mid",
    "IP Defensa": "def_intentados",
    "PC Defensa": "def_completados",
    "PI Defensa": "def_perdidos",
    "%PC Defensa": "pct_pases_def",
}

NIVEL_MAP = {
    "2025-2026 Season": "temporada",
    "1º mitad": "parte",
    "2º mitad": "parte",
    "0-15": "tramo",
    "16-30": "tramo",
    "31-45": "tramo",
    "45+": "tramo",
    "46-60": "tramo",
    "61-75": "tramo",
    "76-90": "tramo",
    "90+": "tramo",
}

SECTION_HEADERS = {"Partidos", "Por Parte", "Por Minutos"}

# Columnas donde "0" es un dato válido (no ausencia de dato)
ZERO_IS_VALID = {"goles_enc", "goles", "tiros", "tiros_puerta", "centros",
                 "faltas", "jugadas_set", "paradas", "tap", "pl", "pa0"}


def _clean_value(val, col_interno: str = ""):
    """Convierte strings de Hudl a float o string limpio."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s in ("", "-"):
        return None
    # "0" es válido en columnas numéricas reales, None solo en separadores
    if s == "0" and col_interno not in ZERO_IS_VALID:
        return None
    # Porcentajes
    if s.endswith("%"):
        try:
            return float(s.replace("%", "").replace(",", "."))
        except ValueError:
            return None
    # Tiempo mm:ss → minutos decimales
    if re.match(r"^\d+:\d{2}$", s):
        parts = s.split(":")
        return int(parts[0]) + int(parts[1]) / 60
    # Números con coma decimal (español)
    s = s.replace('"', "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return s


def _parse_csv_text(content: str) -> pd.DataFrame:
    """Parsea el contenido de un CSV de Hudl y devuelve un DataFrame limpio."""
    source = io.StringIO(content)
    title = source.readline().strip()
    match = re.match(r"CAdF\s+(?:vs|@)\s+(.+?)(?:\s+—|$)", title)
    rival = match.group(1).strip() if match else "Desconocido"

    source.seek(0)
    raw = pd.read_csv(source, header=None, skiprows=1, dtype=str)
    raw.columns = raw.iloc[0].tolist()
    raw = raw.iloc[1:].reset_index(drop=True)

    # Eliminar columnas separadoras (nombre "0")
    cols_to_keep = [c for c in raw.columns if str(c).strip() not in ("0", "nan", "")]
    raw = raw[cols_to_keep]

    # Eliminar filas de cabecera repetidas y filas todo vacías/ceros
    header_mask = raw.iloc[:, 0].isin(SECTION_HEADERS)
    zero_mask   = raw.apply(
        lambda r: all(str(v).strip() in ("0", "", "nan") for v in r), axis=1
    )
    raw = raw[~header_mask & ~zero_mask].reset_index(drop=True)

    rows = []
    for _, row in raw.iterrows():
        tramo_raw = str(row.iloc[0]).strip()
        nivel = (
            "temporada"
            if re.fullmatch(r"\d{4}-\d{4} Season", tramo_raw)
            else NIVEL_MAP.get(tramo_raw, "tramo")
        )
        record    = {"partido": f"CAdF vs {rival}", "rival": rival,
                     "nivel": nivel, "tramo_raw": tramo_raw}
        for col_hudl, col_interno in COL_MAP.items():
            if col_hudl in row.index and col_hudl != "Partidos":
                record[col_interno] = _clean_value(row.get(col_hudl), col_interno)
        rows.append(record)

    return pd.DataFrame(rows)


def _parse_csv(filepath: str) -> pd.DataFrame:
    """Compatibilidad para cargar un CSV de Hudl desde el sistema local."""
    with open(filepath, encoding="utf-8-sig") as source:
        return _parse_csv_text(source.read())


def _load_drive_csvs(folder_id: str, headers: dict[str, str]) -> list[pd.DataFrame]:
    query = f"'{folder_id}' in parents and trashed = false"
    response = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=headers,
        params={
            "q": query,
            "fields": "files(id,name,mimeType)",
            "orderBy": "name",
            "pageSize": 200,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    response.raise_for_status()

    frames = []
    for drive_file in response.json().get("files", []):
        if not drive_file.get("name", "").lower().endswith(".csv"):
            continue
        content = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{drive_file['id']}",
            headers=headers,
            params={"alt": "media", "supportsAllDrives": "true"},
            timeout=60,
        )
        content.raise_for_status()
        frames.append(_parse_csv_text(content.content.decode("utf-8-sig")))
    return frames


def load_all(drive_folder_id: str, drive_headers: dict[str, str]) -> pd.DataFrame:
    """Carga exclusivamente los CSVs de Partidos disponibles en Google Drive."""
    if not drive_folder_id or not drive_headers:
        raise ValueError("Faltan la carpeta o las credenciales para leer los partidos desde Drive.")
    frames = _load_drive_csvs(drive_folder_id, drive_headers)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    tramo_order = [
        "1º mitad", "2º mitad",
        "0-15", "16-30", "31-45", "45+",
        "46-60", "61-75", "76-90", "90+",
    ]
    df["tramo_orden"] = df["tramo_raw"].apply(
        lambda x: 0 if re.fullmatch(r"\d{4}-\d{4} Season", str(x))
        else tramo_order.index(x) + 1 if x in tramo_order else 99
    )
    return df.sort_values(["partido", "tramo_orden"]).reset_index(drop=True)


if __name__ == "__main__":
    print("Ejecuta la aplicación Streamlit para cargar Partidos desde Google Drive.")
