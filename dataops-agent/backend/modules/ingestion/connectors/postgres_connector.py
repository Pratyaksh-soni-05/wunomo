import asyncpg


class PostgresConnector:
    def __init__(self, config: dict):
        self.config = config

    def _dsn(self) -> str:
        c = self.config
        return f"postgresql://{c.get('username', c.get('user', ''))}:{c['password']}@{c['host']}:{c.get('port', 5432)}/{c['database']}"

    def _schema(self) -> str:
        return self.config.get("schema", "public")

    async def list_tables(self) -> list[str]:
        conn = await asyncpg.connect(self._dsn())
        try:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=$1 AND table_type='BASE TABLE'",
                self._schema()
            )
            return [r["table_name"] for r in rows]
        finally:
            await conn.close()

    async def get_schema(self) -> list:
        conn = await asyncpg.connect(self._dsn())
        try:
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=$1 AND table_type='BASE TABLE'",
                self._schema()
            )
            result = []
            for t in tables:
                tname = t["table_name"]
                cols = await conn.fetch(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name=$1 AND table_schema=$2 "
                    "ORDER BY ordinal_position",
                    tname, self._schema()
                )
                count = await conn.fetchval(f'SELECT COUNT(*) FROM "{self._schema()}"."{tname}"')
                result.append({
                    "name": tname,
                    "row_count": count,
                    "columns": [
                        {"name": c["column_name"], "type": c["data_type"],
                         "nullable": c["is_nullable"] == "YES"}
                        for c in cols
                    ]
                })
            return result
        finally:
            await conn.close()

    async def preview(self, table: str, limit: int = 50) -> dict:
        conn = await asyncpg.connect(self._dsn())
        try:
            rows = await conn.fetch(
                f'SELECT * FROM "{self._schema()}"."{table}" LIMIT $1', limit
            )
            cols = list(rows[0].keys()) if rows else []
            return {
                "table": table,
                "columns": cols,
                "rows": [dict(r) for r in rows],
                "count": len(rows)
            }
        finally:
            await conn.close()

    async def execute_sql(self, sql: str) -> dict:
        conn = await asyncpg.connect(self._dsn())
        try:
            rows = await conn.fetch(sql)
            return {"rows": [dict(r) for r in rows], "count": len(rows)}
        finally:
            await conn.close()

    async def sync(self, mode: str = "incremental") -> dict:
        schema = await self.get_schema()
        return {
            "status": "success",
            "mode": mode,
            "tables_synced": len(schema),
            "total_rows": sum(t.get("row_count", 0) for t in schema)
        }