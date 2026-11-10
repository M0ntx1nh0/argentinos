"""Calendario y clasificación del Argentino A en la web pública de la RFFM."""

import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import pandas as pd
import requests
from PIL import Image, ImageOps

SEASON = "2026-2027"
TEAM_ID = "19528575"
PARAMS = {"temporada": "22", "tipojuego": "1", "competicion": "26737706", "grupo": "26737708"}
CALENDAR_URL = f"https://www.rffm.es/competicion/calendario?{urlencode(PARAMS)}"
STANDINGS_URL = f"https://www.rffm.es/competicion/clasificaciones?{urlencode(PARAMS)}"
NEXT_DATA = re.compile(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
LOCAL_DIR = Path(__file__).resolve().parent / "output" / "rffm" / SEASON
CALENDAR_FILE = LOCAL_DIR / "calendario.csv"
STANDINGS_FILE = LOCAL_DIR / "clasificacion.csv"
HISTORY_FILE = LOCAL_DIR / "historial-clasificacion.csv"
CRESTS_DIR = LOCAL_DIR / "escudos"
HISTORY_COLUMNS = ["Jornada", "ID equipo RFFM", "Posición", "Pts"]
GROUP_TEAMS = ["ID local RFFM", "ID visitante RFFM"]
GROUP_COLUMNS = {"Temporada", "Jornada", "Fecha", "Hora", "Local", "Visitante", "Resultado", "Campo",
                 "ID partido RFFM", *GROUP_TEAMS}
CLUB_COLUMNS = ["Temporada", "Jornada", "Fecha", "Hora", "Rival", "Condición", "Resultado", "Campo",
                "ID partido RFFM", "ID rival RFFM"]


def _page_data(html: str) -> dict:
    # Next.js incluye los datos en la respuesta HTML inicial.
    script = NEXT_DATA.search(html)
    if not script:
        raise ValueError("La RFFM no devolvió los datos de la competición.")
    return json.loads(script[1])["props"]["pageProps"]


def parse_calendar(html: str) -> pd.DataFrame:
    page = _page_data(html)
    calendar = page["calendar"]
    if calendar["estado"] != "1" or calendar["temporada"] != SEASON or any(
        page["query"].get(key) != value for key, value in PARAMS.items()
    ):
        raise ValueError("La RFFM devolvió un calendario distinto al solicitado.")

    rows = []
    for round_data in calendar["rounds"]:
        round_date = re.search(r"\d{2}-\d{2}-\d{4}", round_data["jornada"])
        for match in round_data["equipos"]:
            home_goals = str(match["goles_casa"]).strip()
            away_goals = str(match["goles_visitante"]).strip()
            date = match["fecha"] or (round_date[0] if round_date else "")
            rows.append({
                "Temporada": SEASON,
                "Jornada": int(round_data["codjornada"]),
                "Fecha": datetime.strptime(date, "%d-%m-%Y").date().isoformat() if date else "",
                "Hora": match["hora"],
                "Local": match["equipo_local"].strip(),
                "Visitante": match["equipo_visitante"].strip(),
                "Resultado": f"{home_goals}–{away_goals}" if home_goals.isdecimal() and away_goals.isdecimal() else "",
                "Campo": match["campo"],
                "ID partido RFFM": match["codacta"],
                "ID local RFFM": str(match["codigo_equipo_local"]),
                "ID visitante RFFM": str(match["codigo_equipo_visitante"]),
            })
    if not rows:
        raise ValueError("El calendario de la RFFM no incluye partidos del grupo.")
    return pd.DataFrame(rows).sort_values("Jornada", kind="stable", ignore_index=True)


def _club_calendar(group: pd.DataFrame) -> pd.DataFrame:
    if group.duplicated(GROUP_TEAMS).any():
        raise ValueError("El calendario del grupo contiene cruces duplicados.")
    home = group["ID local RFFM"].eq(TEAM_ID)
    club = group.loc[home | group["ID visitante RFFM"].eq(TEAM_ID)].copy()
    if club.empty or club["Jornada"].duplicated().any():
        raise ValueError("El calendario debe incluir un partido del Argentino por cada jornada que disputa.")
    at_home = home.loc[club.index]
    club["Rival"] = club["Visitante"].where(at_home, club["Local"])
    club["Condición"] = at_home.map({True: "Local", False: "Visitante"})
    club["ID rival RFFM"] = club["ID visitante RFFM"].where(at_home, club["ID local RFFM"])
    return club[CLUB_COLUMNS].sort_values("Jornada", ignore_index=True)


def parse_standings(html: str) -> tuple[int, pd.DataFrame]:
    page = _page_data(html)
    standings = page["standings"]
    if (standings["estado"] != "1" or page["season"]["cod_temporada"] != PARAMS["temporada"]
            or standings["codigo_competicion"] != PARAMS["competicion"]
            or standings["codigo_grupo"] != PARAMS["grupo"]):
        raise ValueError("La RFFM devolvió una clasificación distinta a la solicitada.")

    teams = pd.DataFrame(standings["clasificacion"])
    if teams.empty or not teams["codequipo"].eq(TEAM_ID).any():
        raise ValueError("La clasificación de la RFFM no incluye al Argentino.")
    columns = {
        "posicion": "Posición", "nombre": "Equipo", "puntos": "Pts", "jugados": "PJ",
        "ganados": "PG", "empatados": "PE", "perdidos": "PP", "goles_a_favor": "GF",
        "goles_en_contra": "GC", "puntos_sancion": "Sanción", "codequipo": "ID equipo RFFM",
    }
    result = teams[list(columns)].rename(columns=columns)
    numeric = result.columns.difference(["Equipo", "ID equipo RFFM"])
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="raise").astype("Int64")
    result.insert(0, "Temporada", SEASON)
    result.insert(1, "Jornada", int(standings["jornada"]))
    return int(standings["jornada"]), result


def load_competition_calendar(source=CALENDAR_FILE) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Lee el calendario del grupo y conserva la compatibilidad con el CSV anterior."""
    calendar = pd.read_csv(source, sep=";", keep_default_na=False,
                           dtype={column: str for column in ["ID partido RFFM", "ID rival RFFM", *GROUP_TEAMS]})
    if calendar.empty or "Temporada" not in calendar or not calendar["Temporada"].eq(SEASON).all():
        raise ValueError("El CSV de calendario no corresponde a la temporada activa.")
    if GROUP_COLUMNS.issubset(calendar):
        return _club_calendar(calendar), calendar
    if set(CLUB_COLUMNS).issubset(calendar):
        return calendar, None
    raise ValueError("El CSV de calendario no contiene las columnas necesarias.")


def load_calendar(source=CALENDAR_FILE) -> pd.DataFrame:
    club, _ = load_competition_calendar(source)
    return club


def load_standings(source=STANDINGS_FILE) -> tuple[int, pd.DataFrame]:
    table = pd.read_csv(source, sep=";", keep_default_na=False, dtype={"ID equipo RFFM": str})
    columns = {*HISTORY_COLUMNS, "Temporada", "Equipo", "PJ", "PG", "PE", "PP", "GF", "GC"}
    if (table.empty or not columns.issubset(table) or not table["Temporada"].eq(SEASON).all()
            or not table["ID equipo RFFM"].eq(TEAM_ID).any()):
        raise ValueError("El CSV de clasificación no corresponde al grupo del Club Argentino.")
    return int(table["Jornada"].iloc[0]), table


def load_standings_history(standings: pd.DataFrame, source=HISTORY_FILE) -> pd.DataFrame:
    latest = standings[HISTORY_COLUMNS]
    try:
        saved = pd.read_csv(source, sep=";", usecols=HISTORY_COLUMNS, dtype={"ID equipo RFFM": str})
    except (OSError, ValueError):
        return latest.copy()
    history = pd.concat([saved, latest], ignore_index=True).drop_duplicates(
        ["Jornada", "ID equipo RFFM"], keep="last"
    )
    return history[history["Jornada"].le(latest["Jornada"].max())]


def csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False, sep=";").encode("utf-8-sig")


def _write_local(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as folder:
        staged = Path(folder) / path.name
        staged.write_bytes(content)
        staged.replace(path)


def _download_crest(team: dict) -> bool:
    team_id = str(team["codequipo"])
    image_path = team["url_img"]
    if not team_id.isdecimal():
        return False
    target = CRESTS_DIR / f"{team_id}.png"
    if target.is_file():
        return True
    if not image_path or not image_path.startswith("/pnfg/pimg/Clubes/"):
        return False
    try:
        response = requests.get(f"https://appweb.rffm.es{image_path}", timeout=8)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as original:
            crest = ImageOps.exif_transpose(original).convert("RGBA")
            crest.thumbnail((192, 192), Image.Resampling.LANCZOS)
            png = io.BytesIO()
            crest.save(png, format="PNG")
        _write_local(target, png.getvalue())
        return True
    except (requests.RequestException, OSError):
        return False


def _download_standings_round(jornada: int) -> pd.DataFrame | None:
    try:
        response = requests.get(STANDINGS_URL, params={"jornada": jornada}, timeout=12)
        response.raise_for_status()
        actual, standings = parse_standings(response.text)
        if actual == jornada:
            return standings[HISTORY_COLUMNS]
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    return None


def _refresh_standings_history(jornada: int, standings: pd.DataFrame, pool: ThreadPoolExecutor, history_source):
    history = load_standings_history(standings, history_source)
    missing = sorted(set(range(1, jornada)) - set(history["Jornada"]))
    snapshots = [table for table in pool.map(_download_standings_round, missing) if table is not None]
    if snapshots:
        history = pd.concat([history, *snapshots], ignore_index=True)
    _write_local(HISTORY_FILE, csv_bytes(history.sort_values(["Jornada", "Posición"])))


def refresh_local(history_source=HISTORY_FILE) -> tuple[int, int, int]:
    """Descarga la competición y guarda los CSV y escudos en el equipo local."""
    calendar_response = requests.get(CALENDAR_URL, timeout=15)
    calendar_response.raise_for_status()
    standings_response = requests.get(STANDINGS_URL, timeout=15)
    standings_response.raise_for_status()
    calendar = parse_calendar(calendar_response.text)
    club_calendar = _club_calendar(calendar)
    jornada, standings = parse_standings(standings_response.text)
    teams = _page_data(standings_response.text)["standings"]["clasificacion"]
    _write_local(CALENDAR_FILE, csv_bytes(calendar))
    _write_local(STANDINGS_FILE, csv_bytes(standings))
    with ThreadPoolExecutor(max_workers=4) as pool:
        downloaded = sum(pool.map(_download_crest, teams))
        _refresh_standings_history(jornada, standings, pool, history_source)
    return len(club_calendar), len(standings), downloaded


if __name__ == "__main__":
    jornadas, equipos, escudos = refresh_local()
    print(f"{jornadas} jornadas, {equipos} equipos y {escudos} escudos guardados en {LOCAL_DIR}")
