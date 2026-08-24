"""Google Sheets integration boundary.

Thin, synchronous gspread wrapper (callers run it in a thread via
asyncio.to_thread). Auth is a service account whose JSON credentials live in
the environment; the target spreadsheet must be shared with the service
account's email as Editor. Staff access to the data is controlled by whom
the spreadsheet itself is shared with — the bot only writes.
"""

from __future__ import annotations

import json
import logging

import gspread

from app.errors import ExternalServiceError

log = logging.getLogger(__name__)


class SheetsError(ExternalServiceError):
    default_user_message = (
        "Google Sheets is unavailable or misconfigured — check the service "
        "account credentials and that the spreadsheet is shared with it."
    )


class SheetsClient:
    def __init__(self, credentials_json: str, spreadsheet_id: str) -> None:
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise SheetsError("GOOGLE_SHEETS_CREDENTIALS is not valid JSON") from exc
        self._info = info
        self._spreadsheet_id = spreadsheet_id
        self._client: gspread.Client | None = None

    @property
    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}"

    def _spreadsheet(self):
        if self._client is None:
            self._client = gspread.service_account_from_dict(self._info)
        return self._client.open_by_key(self._spreadsheet_id)

    def replace_worksheet(self, title: str, headers: list[str], rows: list[list]) -> int:
        """Create-or-replace one tab with a header row + data rows.

        SYNCHRONOUS — call via asyncio.to_thread. Returns the row count.
        """
        try:
            spreadsheet = self._spreadsheet()
            try:
                worksheet = spreadsheet.worksheet(title)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(
                    title, rows=len(rows) + 10, cols=len(headers) + 2
                )
            worksheet.resize(rows=max(len(rows) + 1, 2), cols=max(len(headers), 1))
            worksheet.clear()
            values = [headers] + [[str(cell) for cell in row] for row in rows]
            worksheet.update(range_name="A1", values=values)
            worksheet.format("1:1", {"textFormat": {"bold": True}})
            return len(rows)
        except SheetsError:
            raise
        except Exception as exc:  # gspread/auth/HTTP errors — keep the boundary clean
            log.exception("Sheets write failed for tab %r", title)
            raise SheetsError(f"sheets write failed: {exc.__class__.__name__}") from exc
