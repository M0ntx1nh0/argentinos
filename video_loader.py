"""Carga los CSV de LongoMatch para el análisis táctico por eventos."""

import io
import re
import unicodedata

import pandas as pd
import requests


def _key(value: str) -> str:
    """Normaliza etiquetas de LongoMatch sin perder el dato original."""
    normalized = unicodedata.normalize("NFKD", str(value))
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char)).upper().split()
    )


def _seconds(value: str) -> float:
    """Convierte el reloj de vídeo de LongoMatch a segundos."""
    try:
        parts = str(value).strip().replace(",", ".").split(":")
        values = [float(part) for part in parts]
        if len(values) == 3:
            return values[0] * 3600 + values[1] * 60 + values[2]
        if len(values) == 2:
            return values[0] * 60 + values[1]
    except ValueError:
        pass
    return 0.0


def _match_details(filename: str) -> tuple[str, str]:
    stem = re.sub(r"\.csv$", "", filename, flags=re.IGNORECASE).strip()
    match = re.match(r"CAdF\s+(?:vs|@)\s+(.+)", stem, flags=re.IGNORECASE)
    rival = match.group(1).strip() if match else stem
    # "CAdF @ Rival (Amistoso)" → el rival sigue siendo "Rival" para cruzarlo con HUDL.
    rival = re.sub(r"\s*[\(\[\-–]?\s*(?:amistoso|pretemporada)\s*[\)\]]?", "", rival,
                   flags=re.IGNORECASE).strip()
    return f"CAdF vs {rival}", rival


def _category_details(category: str) -> tuple[str, str]:
    """Traduce las variantes históricas a fase y perspectiva de equipo."""
    value = _key(category)
    rival = "RIVAL" in value
    team = "rival" if rival else "propio"
    if "INICIO" in value:
        return team, "inicio"
    if "PROGRES" in value or "PROGRE" in value or "ATAQUE" in value:
        return team, "progresion"
    if "FINALIZ" in value:
        return team, "finalizacion"
    if "CORNER" in value:
        return team, "corner"
    if "TIRO LIBRE" in value:
        return team, "tiro_libre"
    if "RECUPER" in value:
        return "propio", "recuperacion"
    if "PERDIDA" in value:
        return "propio", "perdida"
    if "TRAN OFENSIVA" in value:
        return "propio", "transicion_ofensiva"
    if "TRAN DEFENSIVA" in value:
        return "propio", "transicion_defensiva"
    if "GOL" in value:
        return team, "gol"
    if "TARJETA" in value:
        return team, "tarjeta"
    if "SUSTITU" in value:
        return "propio", "sustitucion"
    return team, "otro"


def _selected(tags: set[str], options: dict[str, str]) -> str | None:
    for tag, label in options.items():
        if tag in tags:
            return label
    return None


def parse_longomatch_csv(content: str, filename: str) -> pd.DataFrame:
    """Convierte los bloques CATEGORY de LongoMatch en una tabla de eventos."""
    partido, rival = _match_details(filename)
    lines = [line.rstrip("\r") for line in content.splitlines()]
    events: list[dict] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line.startswith("CATEGORY:"):
            index += 1
            continue

        category = line.split(":", 1)[1].strip()
        index += 1
        if index >= len(lines) or not lines[index].strip():
            continue
        headers = [header.strip() for header in lines[index].split(";")]
        index += 1
        rows: list[list[str]] = []
        while index < len(lines) and not lines[index].startswith("CATEGORY:"):
            if lines[index].strip():
                rows.append(lines[index].split(";"))
            index += 1

        for row in rows:
            values = row + [""] * max(0, len(headers) - len(row))
            fixed = dict(zip(headers[:6], values[:6]))
            tags = {
                _key(header)
                for header, value in zip(headers[6:], values[6:])
                if str(value).strip() in {"1", "1.0"}
            }
            equipo, fase = _category_details(category)
            zona = _selected(tags, {"UNO": "Zona 1", "DOS": "Zona 2", "TRES": "Zona 3"})
            lane = _selected(tags, {
                "IZQUIERDO": "Izquierdo", "IZQUIERDA": "Izquierdo",
                "CENTRAL": "Central", "DERECHO": "Derecho", "DERECHA": "Derecho",
            })
            # El analista etiqueta al rival desde su propia orientación. Lo llevamos
            # a referencia CAdF para poder comparar ambos equipos en el mismo mapa.
            if equipo == "rival" and lane in {"Izquierdo", "Derecho"}:
                lane = "Derecho" if lane == "Izquierdo" else "Izquierdo"
            # Las finalizaciones no llevan tercio en la plantilla: por definición
            # se producen en la zona de finalización de quien ataca.
            if fase == "finalizacion" and zona is None:
                zona = "Zona 3" if equipo == "propio" else "Zona 1"

            events.append({
                "partido": partido,
                "rival": rival,
                "categoria": category,
                "equipo": equipo,
                "fase": fase,
                "nombre": fixed.get("Name", "").strip(),
                "jugador": fixed.get("Player", "").strip() or None,
                "time_seconds": _seconds(fixed.get("Time", "")),
                "time_label": fixed.get("Time", "").strip(),
                "zona": zona,
                "carril": lane,
                "tipo_llegada": _selected(tags, {
                    "CENTRO": "Centro", "PASE FILTRADO": "Pase filtrado", "REMATE": "Remate",
                }),
                "inicio_tipo": _selected(tags, {"CORTO": "Corto", "LARGO": "Largo"}),
                "progresion_tipo": _selected(tags, {"ORGANIZADO": "Organizado", "DIRECTO": "Directo"}),
                "transicion_ofensiva": _selected(tags, {"DIRECTO": "Directo", "REORGANIZA": "Reorganiza"}),
                "transicion_defensiva": _selected(tags, {
                    "PTP": "PTP", "REPLIEGUE": "Repliegue", "MIXTA": "Mixta",
                }),
                "origen_recuperacion_perdida": _selected(tags, {
                    "GENERADA": "Generada", "NO GENERADA": "No generada",
                }),
                "tags": ", ".join(sorted(tags)),
            })

    return pd.DataFrame(events)


def load_longomatch_events(folder_id: str, headers: dict[str, str]) -> pd.DataFrame:
    """Lee únicamente los CSV de LongoMatch de la carpeta Partidos de Drive."""
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
        text = content.content.decode("utf-8-sig")
        if text.lstrip().startswith("CATEGORY:"):
            frames.append(parse_longomatch_csv(text, drive_file["name"]))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(
        ["partido", "time_seconds"]
    ).reset_index(drop=True)
