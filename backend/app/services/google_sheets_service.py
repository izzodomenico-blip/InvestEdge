from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.app.config import get_settings

# Scopes required by the API
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

class GoogleSheetsService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def is_enabled(self) -> bool:
        return self.settings.enable_google_sheets_import

    def get_config(self) -> dict[str, Any]:
        return {
            "enabled": self.is_enabled(),
            "auth_mode": self.settings.google_sheets_auth_mode,
            "credentials_path": str(self.settings.google_sheets_oauth_credentials_path),
            "token_path": str(self.settings.google_sheets_token_path),
            "spreadsheet_id": self.settings.google_sheets_spreadsheet_id,
        }

    def get_credentials(self) -> Credentials | None:
        token_path = self.settings.google_sheets_token_path
        creds = None
        
        if token_path and token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            except Exception:
                # Invalid token file
                pass

        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # Save the refreshed credentials
                    with open(token_path, "w") as token:
                        token.write(creds.to_json())
                except Exception:
                    return None
            else:
                # Authorization required
                return None
        
        return creds

    def authorize_desktop(self) -> str:
        """
        Starts the OAuth flow for desktop app.
        Returns a message or success status.
        """
        creds_path = self.settings.google_sheets_oauth_credentials_path
        token_path = self.settings.google_sheets_token_path
        
        if not creds_path or not creds_path.exists():
            raise FileNotFoundError(f"Google OAuth credentials not found at {creds_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
            
        return "Authorization successful. Token saved."

    def get_sheets_client(self):
        creds = self.get_credentials()
        if not creds:
            raise ValueError("Google Sheets not authorized. Please run authorization flow.")
        return build("sheets", "v4", credentials=creds)

    def read_range(self, range_name: str) -> list[list[Any]]:
        spreadsheet_id = self.settings.google_sheets_spreadsheet_id
        if not spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID not configured in .env")
            
        try:
            service = self.get_sheets_client()
            sheet = service.spreadsheets()
            result = sheet.values().get(spreadsheet_id=spreadsheet_id, range=range_name).execute()
            return result.get("values", [])
        except HttpError as err:
            raise ValueError(f"Google Sheets API error: {err}")
        except Exception as err:
            raise ValueError(f"Error reading Google Sheet: {err}")

    def get_status(self) -> dict[str, Any]:
        creds_path = self.settings.google_sheets_oauth_credentials_path
        token_path = self.settings.google_sheets_token_path
        spreadsheet_id = self.settings.google_sheets_spreadsheet_id
        
        enabled = self.is_enabled()
        creds_configured = creds_path.exists() if creds_path else False
        token_exists = token_path.exists() if token_path else False
        spreadsheet_configured = bool(spreadsheet_id)
        
        connection_ok = False
        message = None
        available_ranges = []
        
        if enabled and creds_configured and token_exists and spreadsheet_configured:
            try:
                # Try a lightweight call to check connection
                # Values.get is read-only
                # We can't really guess ranges without reading metadata
                # but we can try reading the first row of Portfolio if configured
                self.get_sheets_client()
                connection_ok = True
                message = "Connected to Google Sheets API"
                available_ranges = [
                    self.settings.google_sheets_portfolio_range,
                    self.settings.google_sheets_transactions_range,
                    self.settings.google_sheets_cash_range,
                    self.settings.google_sheets_watchlist_range
                ]
            except Exception as e:
                message = str(e)
        elif not enabled:
            message = "Google Sheets import is disabled in settings"
        elif not creds_configured:
            message = f"OAuth credentials file missing at {creds_path}"
        elif not token_exists:
            message = "OAuth token missing. Authorization required."
        elif not spreadsheet_configured:
            message = "Spreadsheet ID not configured."

        return {
            "enabled": enabled,
            "auth_mode": self.settings.google_sheets_auth_mode,
            "credentials_configured": creds_configured,
            "token_exists": token_exists,
            "spreadsheet_configured": spreadsheet_configured,
            "connection_ok": connection_ok,
            "available_ranges": available_ranges,
            "message": message
        }

    def validate_headers(self, rows: list[list[Any]], expected_headers: list[str]) -> list[str]:
        if not rows:
            return ["Sheet is empty"]
            
        headers = [str(h).strip().lower() for h in rows[0]]
        missing = []
        for expected in expected_headers:
            if expected.lower() not in headers:
                missing.append(expected)
        
        if missing:
            return [f"Missing columns: {', '.join(missing)}"]
        return []

    def rows_to_dicts(self, rows: list[list[Any]]) -> list[dict[str, Any]]:
        if not rows or len(rows) < 2:
            return []
            
        headers = [str(h).strip() for h in rows[0]]
        data = []
        
        for row in rows[1:]:
            # Pad row if shorter than headers
            padded_row = row + [None] * (len(headers) - len(row))
            # Slice row if longer than headers
            final_row = padded_row[:len(headers)]
            data.append(dict(zip(headers, final_row)))
            
        return data
