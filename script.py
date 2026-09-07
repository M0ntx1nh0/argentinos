"""
Descarga automática del Training Report de Titan (stats.integratedbionics.com).

Flujo:
1. Lee credenciales de .env (TITAN_USER / TITAN_PASS)
2. Abre Chrome, hace login en Titan
3. Va a Team > Workbooks > Training Report
4. Hace Sync y extrae el ID del Google Sheet
5. Descarga el sheet via Google Sheets API (cuenta de servicio o token OAuth)
6. Renombra el archivo con rango de fechas detectadas
7. Copia a la carpeta local data/GPS
8. Sube o actualiza el archivo en Google Drive

Requisitos:
    pip install playwright openpyxl python-dotenv google-auth google-auth-oauthlib requests
    playwright install chromium
    La cuenta de servicio se usa si existe su archivo JSON. El token OAuth queda como respaldo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

TITAN_URL            = "https://stats.integratedbionics.com/"
TITAN_USER           = os.getenv("TITAN_USER", "")
TITAN_PASS           = os.getenv("TITAN_PASS", "")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

DOWNLOADS            = Path.home() / "Downloads"
TITAN_DESKTOP_FOLDER = Path(__file__).parent / "data" / "GPS"
TOKEN_FILE           = Path(__file__).parent / "token_google.json"
SERVICE_ACCOUNT_FILE = Path(os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    Path(__file__).parent / "titan-argentinos-503811-67466c1aab4b.json",
))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive",
]


# ── Google Auth ───────────────────────────────────────────────────────────────

def get_google_creds() -> Credentials:
    """Usa la cuenta de servicio; mantiene OAuth como respaldo temporal."""
    if SERVICE_ACCOUNT_FILE.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
        )
        creds.refresh(Request())
        return creds

    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            "No se encontró la clave de cuenta de servicio ni token_google.json.\n"
            "Configura GOOGLE_SERVICE_ACCOUNT_FILE o ejecuta: python setup_google.py"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def get_google_token() -> str:
    """Devuelve el access token actual de Google."""
    return get_google_creds().token


def _find_sheet_url_in_context(ctx, timeout_s: int = 20) -> str:
    """Espera a que alguna pestaña del contexto llegue al Google Sheet real."""
    deadline = time.time() + timeout_s
    last_googleish_url = ""

    while time.time() < deadline:
        for open_page in list(ctx.pages):
            try:
                url = (open_page.url or "").strip()
            except Exception:
                continue

            if not url:
                continue
            if "spreadsheets/d/" in url or "spreadsheets%2Fd%2F" in url:
                return url
            if "docs.google.com" in url or "accounts.google.com" in url:
                last_googleish_url = url

        time.sleep(1)

    return last_googleish_url


def _debug_context_pages(ctx) -> None:
    """Imprime las pestañas abiertas del contexto para depurar redirects/popup flows."""
    print("   Pestañas detectadas en el contexto:")
    for idx, open_page in enumerate(list(ctx.pages), start=1):
        try:
            title = (open_page.title() or "").strip()
        except Exception:
            title = ""
        try:
            url = (open_page.url or "").strip()
        except Exception:
            url = ""
        print(f"   [{idx}] title={title!r} url={url!r}")


def _extract_sheet_id(text: str) -> str | None:
    """Extrae el ID del Google Sheet desde una URL directa o una URL con continue=..."""
    if not text:
        return None

    patterns = [
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"spreadsheets%2Fd%2F([a-zA-Z0-9_-]+)",
        r"continue=https://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"continue=https%3A%2F%2Fdocs\.google\.com%2Fspreadsheets%2Fd%2F([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


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
        try:
            sheet_page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except PWTimeout:
            pass

        _debug_context_pages(ctx)
        sheet_url = _find_sheet_url_in_context(ctx, timeout_s=25)
        if not sheet_url:
            print("   No se detectó URL de Google Sheet tras esperar redirects.")
            _debug_context_pages(ctx)
        print(f"   URL: {sheet_url}")
        sheet_id = _extract_sheet_id(sheet_url)
        if not sheet_id:
            for open_page in list(ctx.pages):
                try:
                    candidate = (open_page.url or "").strip()
                except Exception:
                    candidate = ""
                sheet_id = _extract_sheet_id(candidate)
                if sheet_id:
                    break
                try:
                    title = (open_page.title() or "").strip()
                except Exception:
                    title = ""
                sheet_id = _extract_sheet_id(title)
                if sheet_id:
                    break
        browser.close()

    if not sheet_id:
        raise ValueError(f"No se pudo extraer el Sheet ID de: {sheet_url}")

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


def _drive_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_google_token()}"}


def _find_existing_drive_file(file_name: str, folder_id: str = "") -> str | None:
    """Busca un archivo existente en Drive por nombre para actualizarlo."""
    escaped_name = file_name.replace("'", "\\'")
    query_parts = [f"name = '{escaped_name}'", "trashed = false"]
    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")

    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=_drive_headers(),
        params={
            "q": " and ".join(query_parts),
            "fields": "files(id,name)",
            "pageSize": 10,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def upload_file_to_drive(source: Path, file_name: str, folder_id: str = "") -> dict:
    """Sube el Excel a Drive o actualiza uno existente con el mismo nombre."""
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    metadata = {"name": file_name}
    if folder_id:
        metadata["parents"] = [folder_id]

    existing_file_id = _find_existing_drive_file(file_name, folder_id)
    params = {"uploadType": "multipart", "supportsAllDrives": "true"}
    files = {
        "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
        "file": (file_name, source.read_bytes(), mime),
    }

    if existing_file_id:
        print("→ Actualizando archivo en Google Drive...")
        url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_file_id}"
        resp = requests.patch(url, headers=_drive_headers(), params=params, files=files, timeout=120)
    else:
        print("→ Subiendo archivo a Google Drive...")
        url = "https://www.googleapis.com/upload/drive/v3/files"
        resp = requests.post(url, headers=_drive_headers(), params=params, files=files, timeout=120)

    resp.raise_for_status()
    return resp.json()


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
    drive_file  = upload_file_to_drive(final_path, final_name, GOOGLE_DRIVE_FOLDER_ID)
    drive_link  = f"https://drive.google.com/file/d/{drive_file['id']}/view"

    print()
    print("✓ Training Report listo.")
    print(f"  Fechas: {start_date:%d-%m-%Y} → {end_date:%d-%m-%Y}")
    print(f"  Archivo: {final_path}")
    print(f"  Drive: {drive_link}")


if __name__ == "__main__":
    main()
