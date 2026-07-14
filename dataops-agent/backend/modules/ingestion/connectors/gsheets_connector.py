import asyncio
import structlog
from datetime import datetime, timezone
from typing import Any

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _infer_type(values: list) -> str:
    """Infer column type from a sample of values."""
    non_null = [v for v in values if v not in ("", None)]
    if not non_null:
        return "string"
    bools = {"true", "false", "yes", "no"}
    if all(str(v).strip().lower() in bools for v in non_null):
        return "boolean"
    try:
        [int(str(v).replace(",", "")) for v in non_null]
        return "integer"
    except ValueError:
        pass
    try:
        [float(str(v).replace(",", "")) for v in non_null]
        return "float"
    except ValueError:
        pass
    return "string"


class GSheetsConnector:
    """
    Connects to Google Sheets data sources using a service account.

    connection_config keys (stored in DataSource.connection_config JSON):
      - spreadsheet_id (required):   The Google Sheet ID from its URL
      - sheet_name:                  Worksheet tab name (default: first sheet)
      - header_row:                  0-indexed row number for headers (default: 0)
      - credentials_json:            Full service account JSON dict (stored as JSON field)
                                     OR set GOOGLE_APPLICATION_CREDENTIALS env var
      - range_notation:              Optional A1 notation to limit range e.g. "A1:Z1000"
      - skip_empty_rows:             bool (default True)

    Dependencies:
        pip install gspread google-auth
    """

    def __init__(self, connection_config: dict):
        self.config = connection_config
        self.spreadsheet_id = connection_config.get("spreadsheet_id", "")
        self.sheet_name = connection_config.get("sheet_name")
        self.header_row = connection_config.get("header_row", 0)
        self.range_notation = connection_config.get("range_notation")
        self.skip_empty = connection_config.get("skip_empty_rows", True)
        self._client = None
        self._sheet = None

    # ------------------------------------------------------------------
    # Internal: auth + open sheet (runs in thread since gspread is sync)
    # ------------------------------------------------------------------

    def _open_sheet_sync(self):
        """Open gspread client and worksheet synchronously."""
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError:
            raise ImportError(
                "gspread and google-auth are required for Google Sheets connector. "
                "Run: pip install gspread google-auth"
            )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]

        creds_json = self.config.get("credentials_json")
        if creds_json:
            if isinstance(creds_json, str):
                import json
                creds_json = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        else:
            # Fall back to application default credentials
            import google.auth
            creds, _ = google.auth.default(scopes=scopes)

        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self.spreadsheet_id)

        if self.sheet_name:
            worksheet = spreadsheet.worksheet(self.sheet_name)
        else:
            worksheet = spreadsheet.get_worksheet(0)

        return worksheet

    async def _get_worksheet(self):
        """Async wrapper: open worksheet in thread pool."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self._open_sheet_sync
        )

    def _fetch_records_sync(self, worksheet) -> tuple[list[str], list[list]]:
        """Fetch all values and split into headers + data rows."""
        if self.range_notation:
            all_values = worksheet.get(self.range_notation)
        else:
            all_values = worksheet.get_all_values()

        if not all_values:
            return [], []

        headers = [str(h).strip() for h in all_values[self.header_row]]
        data_rows = all_values[self.header_row + 1 :]

        if self.skip_empty:
            data_rows = [row for row in data_rows if any(cell.strip() for cell in row)]

        return headers, data_rows

    async def _get_all_values(self) -> tuple[list[str], list[list]]:
        """Async wrapper for fetching all values."""
        worksheet = await self._get_worksheet()
        return await asyncio.get_event_loop().run_in_executor(
            None, self._fetch_records_sync, worksheet
        )

    def _rows_to_dicts(self, headers: list[str], rows: list[list]) -> list[dict]:
        """Convert list-of-lists to list-of-dicts, aligning by header."""
        result = []
        for row in rows:
            # Pad or truncate row to match header count
            padded = list(row) + [""] * max(0, len(headers) - len(row))
            record = {headers[i]: padded[i] for i in range(len(headers))}
            result.append(record)
        return result

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_schema(self) -> dict:
        """
        Reads the sheet header row + first 50 rows to infer column types.
        Returns: { "table_name": sheet_name, "columns": [{name, type, nullable}], "row_count_estimate": N }
        """
        log.info("gsheets_connector.get_schema", spreadsheet_id=self.spreadsheet_id)
        try:
            headers, data_rows = await self._get_all_values()
            if not headers:
                return {"error": "No headers found in Google Sheet"}

            sample_rows = data_rows[:50]
            columns = []
            for i, header in enumerate(headers):
                sample_values = [
                    row[i] if i < len(row) else "" for row in sample_rows
                ]
                col_type = _infer_type(sample_values)
                columns.append({
                    "name": header,
                    "type": col_type,
                    "nullable": True,
                })

            sheet_label = self.sheet_name or "Sheet1"
            return {
                "table_name": sheet_label,
                "columns": columns,
                "row_count_estimate": len(data_rows),
                "spreadsheet_id": self.spreadsheet_id,
            }
        except Exception as exc:
            log.error("gsheets_connector.get_schema.error", error=str(exc))
            return {"error": str(exc)}

    async def preview(self, limit: int = 10) -> dict:
        """
        Returns first `limit` rows as a list of dicts.
        """
        log.info("gsheets_connector.preview", limit=limit)
        try:
            headers, data_rows = await self._get_all_values()
            if not headers:
                return {"error": "No headers found"}
            preview_rows = self._rows_to_dicts(headers, data_rows[:limit])
            schema = await self.get_schema()
            return {
                "rows": preview_rows,
                "row_count": len(preview_rows),
                "columns": schema.get("columns", []),
            }
        except Exception as exc:
            log.error("gsheets_connector.preview.error", error=str(exc))
            return {"error": str(exc)}

    async def sync(self) -> dict:
        """
        Fetches all rows from the sheet.
        Returns: { "rows": [...], "total_rows": N, "columns": [...], "synced_at": ... }
        """
        log.info("gsheets_connector.sync", spreadsheet_id=self.spreadsheet_id)
        try:
            headers, data_rows = await self._get_all_values()
            if not headers:
                return {"error": "No headers found in Google Sheet"}

            rows = self._rows_to_dicts(headers, data_rows)
            schema = await self.get_schema()

            log.info("gsheets_connector.sync.done", total_rows=len(rows))
            return {
                "rows": rows,
                "total_rows": len(rows),
                "columns": schema.get("columns", []),
                "synced_at": utcnow().isoformat(),
                "spreadsheet_id": self.spreadsheet_id,
                "sheet_name": self.sheet_name or "Sheet1",
            }
        except Exception as exc:
            log.error("gsheets_connector.sync.error", error=str(exc))
            return {"error": str(exc)}

    async def list_sheets(self) -> dict:
        """
        Returns all worksheet tab names in the spreadsheet.
        Useful for letting users pick which sheet to connect to.
        """
        log.info("gsheets_connector.list_sheets", spreadsheet_id=self.spreadsheet_id)
        try:
            def _list_sync():
                try:
                    import gspread
                    from google.oauth2.service_account import Credentials
                except ImportError:
                    raise ImportError("gspread and google-auth required")

                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly",
                ]
                creds_json = self.config.get("credentials_json")
                if creds_json:
                    if isinstance(creds_json, str):
                        import json
                        creds_json = json.loads(creds_json)
                    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
                else:
                    import google.auth
                    creds, _ = google.auth.default(scopes=scopes)
                client = gspread.authorize(creds)
                spreadsheet = client.open_by_key(self.spreadsheet_id)
                return [ws.title for ws in spreadsheet.worksheets()]

            sheets = await asyncio.get_event_loop().run_in_executor(None, _list_sync)
            return {"sheets": sheets, "count": len(sheets)}
        except Exception as exc:
            log.error("gsheets_connector.list_sheets.error", error=str(exc))
            return {"error": str(exc)}