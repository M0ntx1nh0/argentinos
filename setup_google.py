"""
Setup de Google Sheets API — ejecutar UNA SOLA VEZ.

Abre el navegador para que autorices el acceso a tu Google Drive.
Guarda un token en token_google.json que el script principal usará siempre.

Pasos previos (solo la primera vez):
  1. Ve a https://console.cloud.google.com/
  2. Crea un proyecto (o usa uno existente)
  3. Activa la API: APIs y servicios > Biblioteca > "Google Sheets API" > Activar
  4. Crea credenciales: APIs y servicios > Credenciales > Crear credenciales > ID de cliente OAuth
     - Tipo: Aplicación de escritorio
     - Descarga el JSON y guárdalo como credentials_google.json en esta carpeta
  5. Ejecuta:  python setup_google.py
"""

from pathlib import Path
import gspread
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import json

SCOPES        = ["https://www.googleapis.com/auth/spreadsheets.readonly",
                 "https://www.googleapis.com/auth/drive.readonly"]
CREDS_FILE    = Path(__file__).parent / "credentials_google.json"
TOKEN_FILE    = Path(__file__).parent / "token_google.json"


def main():
    if not CREDS_FILE.exists():
        print("ERROR: No se encontró credentials_google.json")
        print("Sigue los pasos del docstring de este archivo para crearlo.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"✓ Token guardado en {TOKEN_FILE}")
    print("  Ya puedes ejecutar script.py normalmente.")


if __name__ == "__main__":
    main()
