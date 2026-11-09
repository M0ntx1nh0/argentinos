"""Carga los CSV de LongoMatch para el análisis táctico por eventos."""

import io
import re
import unicodedata

import pandas as pd
from data_loader import iter_drive_csvs


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
    # Algunos CSV se exportan con el nombre del archivo de HUDL:
    # "CAdF @ UDA - Todos Atletas - Promedios" → rival "UDA".
    stem = re.split(r"\s+[—–-]\s+Todos Atletas", stem, maxsplit=1, flags=re.IGNORECASE)[0].strip()
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
    # "INICIO 1T"/"INICIO 2T" marcan el comienzo de cada parte, no un inicio de juego.
    if re.fullmatch(r"INICIO [12] ?T", value):
        return "partido", "inicio_parte"
    if "ASISTENCIA" in value:
        return "propio", "asistencia"
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


PLAYER_TAG = re.compile(r"^([A-Z][A-Z ]*?)\s+(\d{1,2})$")


def _player_tag(tags: set[str]) -> str | None:
    """Etiqueta con nombre y dorsal ("SOLDATI 20"): el jugador que remata."""
    for tag in sorted(tags):
        if PLAYER_TAG.match(tag):
            return tag
    return None


def _dorsal(value: str | None) -> str | None:
    if not value:
        return None
    found = re.match(r"^(\d{1,2})\s*-", value) or PLAYER_TAG.match(value)
    if not found:
        return None
    return found.group(1) if found.re is not PLAYER_TAG else found.group(2)


def _canonical_players(events: pd.DataFrame) -> pd.DataFrame:
    """Unifica jugadores por dorsal: el nombre más usado en la columna Player
    ("7-Lucas Appiolaza") sustituye variantes y etiquetas ("APPIOLAZZA 7")."""
    players = events["jugador"].dropna()
    players = players[~players.str.contains(r"\bPlayer\b", case=False)]
    roster = (pd.DataFrame({"dorsal": players.map(_dorsal), "nombre": players})
              .dropna().groupby("dorsal")["nombre"].agg(lambda s: s.value_counts().index[0]).to_dict())

    def canonical(value):
        if not isinstance(value, str) or not value or re.search(r"\bPlayer\b", value, re.IGNORECASE):
            return None
        dorsal = _dorsal(value)
        if dorsal in roster:
            return roster[dorsal]
        tag = PLAYER_TAG.match(value)
        return f"{tag.group(2)}-{tag.group(1).title()}" if tag else value

    events["jugador"] = events["jugador"].map(canonical)
    events["rematador"] = events["rematador"].map(canonical)
    events["pasador"] = events["pasador"].map(canonical)
    return events


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
                "archivo": filename,
                "categoria": category,
                "equipo": equipo,
                "fase": fase,
                "nombre": fixed.get("Name", "").strip(),
                # Player = quien da el pase/centro o ejecuta; la etiqueta con nombre = quien remata.
                "jugador": " ".join(fixed.get("Player", "").split()) or None,
                "rematador": _player_tag(tags),
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
                    "NO GENERADA": "No generada", "GENERADA": "Generada",
                }),
                # Etiquetas añadidas en octubre de 2026.
                "remate": _selected(tags, {"NO REMATA": "No remata", "REMATA": "Remata"}),
                "destino_bp": _selected(tags, {
                    "PRIMER PALO": "Primer palo", "PUNTO PENAL": "Punto de penalti",
                    "SEGUNDO PALO": "Segundo palo",
                }),
                "zona_falta": _selected(tags, {
                    "DIRECTA": "Directa", "FRONTAL": "Frontal", "MEDIALUNA": "Frontal",
                    "LATERAL": "Lateral", "LEJANA": "Lejana",
                }),
                # Cómo se ejecuta el balón parado: en corto, disparo directo o envío al área.
                "ejecucion_bp": (
                    None if fase not in ("corner", "tiro_libre")
                    else "Corto" if "CORTO" in tags
                    else "Remate directo" if "REMATE" in tags
                    else "Al área"
                ),
                "rol_transicion": _selected(tags, {
                    "INFLUENCIA": "Influencia", "COOPERACION": "Cooperación", "VIGILANCIA": "Vigilancia",
                }),
                "tags": ", ".join(sorted(tags)),
            })

    return pd.DataFrame(events)


def load_longomatch_events(folder_id: str, headers: dict[str, str]) -> pd.DataFrame:
    """Lee únicamente los CSV de LongoMatch de la carpeta Partidos de Drive."""
    return read_longomatch_reports(iter_drive_csvs(folder_id, headers))


def read_longomatch_reports(csvs) -> pd.DataFrame:
    frames = [parse_longomatch_csv(text, name) for name, text, _ in csvs
              if text.lstrip().startswith("CATEGORY:")]
    if not frames:
        return pd.DataFrame()
    events = pd.concat(frames, ignore_index=True).sort_values(
        ["partido", "time_seconds"]
    ).reset_index(drop=True)
    # Una llegada cuyo tipo es "Remate" ya es un remate: el analista no repite la etiqueta "Remata".
    implied = (events["fase"] == "finalizacion") & (events["tipo_llegada"] == "Remate") & events["remate"].isna()
    events["remate_inferido"] = implied
    events.loc[implied, "remate"] = "Remata"
    # Criterio del analista: en una llegada de tipo «Remate», Player es quien dispara
    # (no hay pase previo). Se guarda como rematador y no como pasador.
    direct = (events["fase"] == "finalizacion") & (events["tipo_llegada"] == "Remate")
    events.loc[direct & events["rematador"].isna(), "rematador"] = events.loc[direct, "jugador"]
    events["pasador"] = events["jugador"].where((events["fase"] == "finalizacion") & ~direct)
    return _canonical_players(events)
