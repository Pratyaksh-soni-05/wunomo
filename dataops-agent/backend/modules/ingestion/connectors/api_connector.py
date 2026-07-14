import asyncio
import structlog
import httpx
from datetime import datetime, timezone
from typing import Any

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class APIConnector:
    """
    Connects to REST API data sources.

    connection_config keys (stored in DataSource.connection_config JSON):
      - base_url (required):       e.g. "https://api.example.com/v1"
      - endpoint (required):       e.g. "/reports/daily"
      - method:                    "GET" (default) | "POST"
      - auth_type:                 "none" | "bearer" | "api_key" | "basic" (default: none)
      - auth_token:                Bearer token value
      - api_key_header:            Header name for API key (e.g. "X-Api-Key")
      - api_key_value:             API key value
      - basic_username:            Basic auth username
      - basic_password:            Basic auth password
      - headers:                   dict of additional headers
      - body:                      dict payload for POST requests
      - params:                    dict of query params
      - data_path:                 dot-path to the records array in response JSON
                                   e.g. "data.results" → response["data"]["results"]
      - pagination_type:           "none" | "page" | "cursor" | "offset"
      - page_param:                query param name for page number (default: "page")
      - page_size_param:           query param name for page size (default: "per_page")
      - page_size:                 int, records per page (default: 100)
      - cursor_path:               dot-path to next cursor in response JSON
      - cursor_param:              query param name for cursor (default: "cursor")
      - offset_param:              query param name for offset (default: "offset")
      - max_pages:                 safety cap (default: 20)
      - timeout_seconds:           per-request timeout (default: 30)
    """

    def __init__(self, connection_config: dict):
        self.config = connection_config
        self.base_url = connection_config.get("base_url", "").rstrip("/")
        self.endpoint = connection_config.get("endpoint", "")
        self.method = connection_config.get("method", "GET").upper()
        self.timeout = connection_config.get("timeout_seconds", 30)
        self.max_pages = connection_config.get("max_pages", 20)

    # ------------------------------------------------------------------
    # Auth headers builder
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.config.get("headers") or {})
        auth_type = self.config.get("auth_type", "none").lower()
        if auth_type == "bearer":
            token = self.config.get("auth_token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_header = self.config.get("api_key_header", "X-Api-Key")
            key_value = self.config.get("api_key_value", "")
            headers[key_header] = key_value
        return headers

    def _build_auth(self):
        auth_type = self.config.get("auth_type", "none").lower()
        if auth_type == "basic":
            return (
                self.config.get("basic_username", ""),
                self.config.get("basic_password", ""),
            )
        return None

    # ------------------------------------------------------------------
    # Response data extraction
    # ------------------------------------------------------------------

    def _extract_records(self, response_json: Any) -> list[dict]:
        """Follow dot-path from config to extract the records list."""
        data_path = self.config.get("data_path", "")
        if not data_path:
            # If response is already a list, return it
            if isinstance(response_json, list):
                return response_json
            # Try common keys
            for key in ("data", "results", "records", "items", "rows"):
                if isinstance(response_json, dict) and key in response_json:
                    val = response_json[key]
                    if isinstance(val, list):
                        return val
            return [response_json] if isinstance(response_json, dict) else []
        # Traverse dot-path
        node = response_json
        for part in data_path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return []
        return node if isinstance(node, list) else ([node] if node else [])

    def _extract_cursor(self, response_json: Any) -> str | None:
        cursor_path = self.config.get("cursor_path", "")
        if not cursor_path:
            return None
        node = response_json
        for part in cursor_path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return str(node) if node else None

    # ------------------------------------------------------------------
    # Single request
    # ------------------------------------------------------------------

    async def _make_request(self, params: dict = None, body: dict = None) -> dict:
        url = f"{self.base_url}{self.endpoint}"
        headers = self._build_headers()
        auth = self._build_auth()
        merged_params = {**(self.config.get("params") or {}), **(params or {})}
        merged_body = {**(self.config.get("body") or {}), **(body or {})}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if self.method == "GET":
                    resp = await client.get(
                        url,
                        headers=headers,
                        params=merged_params,
                        auth=auth,
                    )
                elif self.method == "POST":
                    resp = await client.post(
                        url,
                        headers=headers,
                        params=merged_params,
                        json=merged_body if merged_body else None,
                        auth=auth,
                    )
                else:
                    return {"error": f"Unsupported method: {self.method}"}

                resp.raise_for_status()
                return resp.json()

        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_schema(self) -> dict:
        """
        Infers schema by fetching the first page and inspecting column types.
        Returns: { "table_name": endpoint, "columns": [ {name, type} ] }
        """
        log.info("api_connector.get_schema", url=self.base_url + self.endpoint)
        try:
            resp = await self._make_request()
            if "error" in resp:
                return resp
            records = self._extract_records(resp)
            if not records:
                return {"error": "No records returned — cannot infer schema"}
            sample = records[0]
            columns = []
            for k, v in sample.items():
                if isinstance(v, bool):
                    col_type = "boolean"
                elif isinstance(v, int):
                    col_type = "integer"
                elif isinstance(v, float):
                    col_type = "float"
                elif isinstance(v, dict) or isinstance(v, list):
                    col_type = "json"
                else:
                    col_type = "string"
                columns.append({"name": k, "type": col_type, "nullable": True})
            return {
                "table_name": self.endpoint.strip("/").replace("/", "_"),
                "columns": columns,
                "sample_row_count": len(records),
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def preview(self, limit: int = 10) -> dict:
        """Fetch first `limit` records for preview."""
        log.info("api_connector.preview", limit=limit)
        try:
            size_param = self.config.get("page_size_param", "per_page")
            page_param = self.config.get("page_param", "page")
            params = {size_param: min(limit, 100), page_param: 1}
            resp = await self._make_request(params=params)
            if "error" in resp:
                return resp
            records = self._extract_records(resp)[:limit]
            schema = await self.get_schema()
            return {
                "rows": records,
                "row_count": len(records),
                "columns": schema.get("columns", []),
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def sync(self) -> dict:
        """
        Fetches all records across all pages and returns them.
        Supports page-based, cursor-based, and offset-based pagination.
        Caps at max_pages for safety.

        Returns: { "rows": [...], "total_rows": N, "pages_fetched": N }
        """
        log.info("api_connector.sync", url=self.base_url + self.endpoint)
        pagination_type = self.config.get("pagination_type", "none").lower()
        page_size = self.config.get("page_size", 100)
        all_records = []
        pages_fetched = 0

        try:
            if pagination_type == "none":
                resp = await self._make_request()
                if "error" in resp:
                    return resp
                all_records = self._extract_records(resp)
                pages_fetched = 1

            elif pagination_type == "page":
                page_param = self.config.get("page_param", "page")
                size_param = self.config.get("page_size_param", "per_page")
                page = 1
                while pages_fetched < self.max_pages:
                    resp = await self._make_request(params={page_param: page, size_param: page_size})
                    if "error" in resp:
                        break
                    records = self._extract_records(resp)
                    if not records:
                        break
                    all_records.extend(records)
                    pages_fetched += 1
                    page += 1
                    if len(records) < page_size:
                        break  # last page
                    await asyncio.sleep(0.1)  # be polite

            elif pagination_type == "cursor":
                cursor_param = self.config.get("cursor_param", "cursor")
                size_param = self.config.get("page_size_param", "per_page")
                cursor = None
                while pages_fetched < self.max_pages:
                    params = {size_param: page_size}
                    if cursor:
                        params[cursor_param] = cursor
                    resp = await self._make_request(params=params)
                    if "error" in resp:
                        break
                    records = self._extract_records(resp)
                    if not records:
                        break
                    all_records.extend(records)
                    pages_fetched += 1
                    cursor = self._extract_cursor(resp)
                    if not cursor:
                        break
                    await asyncio.sleep(0.1)

            elif pagination_type == "offset":
                offset_param = self.config.get("offset_param", "offset")
                size_param = self.config.get("page_size_param", "per_page")
                offset = 0
                while pages_fetched < self.max_pages:
                    resp = await self._make_request(params={offset_param: offset, size_param: page_size})
                    if "error" in resp:
                        break
                    records = self._extract_records(resp)
                    if not records:
                        break
                    all_records.extend(records)
                    pages_fetched += 1
                    offset += len(records)
                    if len(records) < page_size:
                        break
                    await asyncio.sleep(0.1)

            log.info(
                "api_connector.sync.done",
                total_rows=len(all_records),
                pages_fetched=pages_fetched,
            )
            return {
                "rows": all_records,
                "total_rows": len(all_records),
                "pages_fetched": pages_fetched,
                "synced_at": utcnow().isoformat(),
            }

        except Exception as exc:
            return {"error": str(exc)}