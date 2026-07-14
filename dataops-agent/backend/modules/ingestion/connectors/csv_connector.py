import pandas as pd
from pathlib import Path


class CSVConnector:
    def __init__(self, config: dict):
        self.file_path = config.get("file_path", "")
        self.sep = config.get("separator", ",")

    def _load(self) -> pd.DataFrame:
        p = Path(self.file_path)
        if p.suffix.lower() in (".xlsx", ".xls"):
            return pd.read_excel(self.file_path)
        return pd.read_csv(self.file_path, sep=self.sep)

    async def get_schema(self) -> list:
        df = self._load()
        return [{"name": "main", "row_count": len(df),
                 "columns": [{"name": c, "type": str(df[c].dtype),
                               "nullable": bool(df[c].isnull().any())} for c in df.columns]}]

    async def preview(self, table="main", limit=50) -> dict:
        df = self._load()
        return {"table": table, "rows": df.head(limit).to_dict("records"), "count": min(limit, len(df))}

    async def sync(self, mode="full") -> dict:
        df = self._load()
        return {"mode": mode, "tables_synced": 1, "total_rows": len(df), "status": "success"}
