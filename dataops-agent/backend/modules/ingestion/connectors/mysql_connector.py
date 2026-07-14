import asyncio
import pymysql


class MySQLConnector:
    def __init__(self, config: dict):
        self.config = config

    def _get_connection(self):
        c = self.config
        return pymysql.connect(
            host=c["host"],
            user=c["user"],
            password=c["password"],
            database=c["database"],
            port=c.get("port", 3306),
            cursorclass=pymysql.cursors.DictCursor
        )

    # ── SCHEMA ────────────────────────────────────────────────────────────────
    def _get_schema_sync(self) -> list:
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_type='BASE TABLE'",
                    (self.config["database"],)
                )
                tables = cursor.fetchall()
                result = []
                for t in tables:
                    tname = t["table_name"]
                    cursor.execute(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name=%s AND table_schema=%s "
                        "ORDER BY ordinal_position",
                        (tname, self.config["database"])
                    )
                    cols = cursor.fetchall()
                    cursor.execute(f"SELECT COUNT(*) as count FROM `{tname}`")
                    count = cursor.fetchone()["count"]
                    result.append({
                        "name": tname,
                        "row_count": count,
                        "columns": [
                            {
                                "name":     c["column_name"],
                                "type":     c["data_type"],
                                "nullable": c["is_nullable"] == "YES"
                            }
                            for c in cols
                        ]
                    })
                return result
        finally:
            conn.close()

    async def get_schema(self) -> list:
        return await asyncio.to_thread(self._get_schema_sync)

    # ── PREVIEW ───────────────────────────────────────────────────────────────
    def _preview_sync(self, table: str, limit: int) -> dict:
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM `{table}` LIMIT %s", (limit,))
                rows = cursor.fetchall()
                cols = list(rows[0].keys()) if rows else []   # ← added
                return {
                    "table":   table,
                    "columns": cols,                           # ← added
                    "rows":    list(rows),
                    "count":   len(rows)
                }
        finally:
            conn.close()

    async def preview(self, table: str, limit: int = 50) -> dict:
        return await asyncio.to_thread(self._preview_sync, table, limit)

    # ── EXECUTE SQL ───────────────────────────────────────────────────────────
    def _execute_sql_sync(self, sql: str) -> dict:
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
                cols = list(rows[0].keys()) if rows else []   # ← added
                return {
                    "columns": cols,                           # ← added
                    "rows":    list(rows),
                    "count":   len(rows)
                }
        finally:
            conn.close()

    async def execute_sql(self, sql: str) -> dict:
        return await asyncio.to_thread(self._execute_sql_sync, sql)

    # ── SYNC ──────────────────────────────────────────────────────────────────
    async def sync(self, mode: str = "incremental") -> dict:
        schema = await self.get_schema()
        return {
            "status":        "success",
            "mode":          mode,
            "tables_synced": len(schema),
            "total_rows":    sum(t.get("row_count", 0) for t in schema)
        }