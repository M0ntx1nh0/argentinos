"""
Descarga automática del Training Report de Titan (stats.integratedbionics.com).

Flujo:
1. Lee credenciales de .env (TITAN_USER / TITAN_PASS)
2. Abre Chrome, hace login en Titan
3. Va a Team > Workbooks > Training Report
4. Hace Sync y extrae el ID del Google Sheet
5. Descarga el sheet via Google Sheets API (token_google.json)
6. Renombra el archivo con rango de fechas detectadas
7. Copia a la carpeta TITAN del escritorio

Requisitos:
    pip install playwright openpyxl python-dotenv gspread google-auth-oauthlib
    playwright install chromium
    python setup_google.py   ← ejecutar UNA SOLA VEZ para obtener token_google.json
"""

from __future__ import annotations

import io
import os
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

TITAN_URL            = "https://stats.integratedbionics.com/"
TITAN_USER           = os.getenv("TITAN_USER", "")
TITAN_PASS           = os.getenv("TITAN_PASS", "")

DOWNLOADS            = Path.home() / "Downloads"
TITAN_DESKTOP_FOLDER = Path(__file__).parent / "data" / "GPS"
TOKEN_FILE           = Path(__file__).parent / "token_google.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly"]


# ── Google Auth ───────────────────────────────────────────────────────────────

def get_google_token() -> str:
    """Carga el token de Google y lo refresca si ha expirado."""
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            "No se encontró token_google.json.\n"
            "Ejecuta primero:  python setup_google.py"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds.token


# ── Titan: obtener Sheet ID ───────────────────────────────────────────────────

def get_sheet_id_from_titan() -> str:
    """Hace login en Titan, abre el Workbook y devuelve el ID del Google Sheet."""

    if not TITAN_USER or not TITAN_PASS or "aqui" in TITAN_PASS:
        raise ValueError("Edita app/.env con TITAN_USER y TITAN_PASS reales.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx     = browser.new_context()
        page    = ctx.new_page()

        # Login Titan (Auth0 de Hudl — flujo en 2 pasos)
        print("→ Login Titan (email)...")
        page.goto(TITAN_URL, timeout=30_000)
        page.wait_for_load_state("networkidle")
        page.fill('input[type="email"]', TITAN_USER)
        page.click('button[type="submit"]')
        page.wait_for_selector('input[type="password"]', timeout=15_000)

        print("→ Login Titan (contraseña)...")
        page.fill('input[type="password"]', TITAN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=20_000)

        # Navegar a Workbooks
        print("→ Abriendo Workbooks...")
        try:
            page.click("text=Team", timeout=8_000)
            page.click("text=Workbooks", timeout=8_000)
        except PWTimeout:
            page.goto(TITAN_URL + "workbooks", timeout=15_000)
        page.wait_for_load_state("networkidle")

        # Abrir Training Report
        print("→ Abriendo Training Report...")
        page.click("text=Training Report", timeout=10_000)
        page.wait_for_load_state("networkidle")

        # Sync
        print("→ Sync...")
        try:
            page.click("text=Sync", timeout=8_000)
            time.sleep(5)
        except PWTimeout:
            print("   (sin botón Sync, continuando...)")

        # Capturar URL del Google Sheet cuando se abre
        print("→ Obteniendo URL del Google Sheet...")
        with ctx.expect_page() as new_page_info:
            page.click("text=Open", timeout=10_000)
        sheet_page = new_page_info.value
        sheet_page.wait_for_load_state("domcontentloaded", timeout=20_000)

        sheet_url = sheet_page.url
        print(f"   URL: {sheet_url}")
        browser.close()

    # Extraer ID del Sheet (de la URL directa o del parámetro "continue")
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", sheet_url)
    if not match:
        match = re.search(r"spreadsheets%2Fd%2F([a-zA-Z0-9_-]+)", sheet_url)
    if not match:
        raise ValueError(f"No se pudo extraer el Sheet ID de: {sheet_url}")

    sheet_id = match.group(1)
    print(f"   Sheet ID: {sheet_id}")
    return sheet_id


# ── Descarga via API ──────────────────────────────────────────────────────────

def download_sheet_as_xlsx(sheet_id: str) -> Path:
    """Descarga el Google Sheet como .xlsx usando el token OAuth."""
    token   = get_google_token()
    url     = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    headers = {"Authorization": f"Bearer {token}"}

    print("→ Descargando Excel via Google API...")
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()

    dest = DOWNLOADS / "Training Report.xlsx"
    dest.write_bytes(resp.content)
    print(f"   Guardado en: {dest}")
    return dest


# ── Procesado local ───────────────────────────────────────────────────────────

def extract_dates_from_workbook(path: Path) -> tuple[date, date]:
    import openpyxl
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    dates: list[date] = []

    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, datetime):
                    dates.append(value.date())
                elif isinstance(value, date):
                    dates.append(value)
                elif isinstance(value, str):
                    for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", value):
                        month, day, year = map(int, match.groups())
                        try:
                            d = date(year, month, day)
                            if d.year >= 2020:
                                dates.append(d)
                        except ValueError:
                            pass

    if not dates:
        raise ValueError(f"No se encontraron fechas en {path.name}.")
    return min(dates), max(dates)


def build_final_name(start: date, end: date) -> str:
    return f"Training Report ({start:%d-%m-%Y} al {end:%d-%m-%Y}).xlsx"


def copy_to_titan_folder(source: Path, final_name: str) -> Path:
    TITAN_DESKTOP_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = TITAN_DESKTOP_FOLDER / final_name
    shutil.copy2(source, destination)
    return destination


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sheet_id    = get_sheet_id_from_titan()
    report_path = download_sheet_as_xlsx(sheet_id)

    start_date, end_date = extract_dates_from_workbook(report_path)
    final_name  = build_final_name(start_date, end_date)
    final_path  = copy_to_titan_folder(report_path, final_name)

    print()
    print("✓ Training Report listo.")
    print(f"  Fechas: {start_date:%d-%m-%Y} → {end_date:%d-%m-%Y}")
    print(f"  Archivo: {final_path}")
    print()
    print("Sube a Google Drive:")
    print("  Compartido conmigo > CLUB ARGENTINO V1 > 5. Titan")


if __name__ == "__main__":
    main()
