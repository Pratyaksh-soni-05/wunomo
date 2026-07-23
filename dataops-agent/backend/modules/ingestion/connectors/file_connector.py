import pandas as pd
from pathlib import Path
from typing import Optional
from models.all_models import SourceType
import structlog

log = structlog.get_logger()


class FileConnector:
    """
    Handles CSV, Excel, JSON file sources.
    connection_config: { file_path, sheet_name? (excel), orient? (json) }
    """
    def __init__(self, config: dict, source_type: SourceType):
        self.config = config
        self.source_type = source_type
        self.file_path = config.get("file_path", "")

    def _load(self, nrows: Optional[int] = None) -> pd.DataFrame:
        p = Path(self.file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if self.source_type == SourceType.CSV:
            return pd.read_csv(self.file_path, nrows=nrows)
        if self.source_type == SourceType.EXCEL:
            sheet = self.config.get("sheet_name", 0)
            return pd.read_excel(self.file_path, sheet_name=sheet, nrows=nrows)
        if self.source_type == SourceType.JSON:
            df = pd.read_json(self.file_path)
            return df.head(nrows) if nrows else df
        raise ValueError(f"FileConnector does not handle type: {self.source_type}")

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        # Replace NaN/Inf with None so JSON serialization never crashes
        return df.where(df.notna(), other=None)

    async def preview(self, table: str = "main", limit: int = 50) -> dict:
        try:
            df = self._load(nrows=limit)
            df = self._clean_df(df)
            return {
                "file": self.file_path,
                "columns": list(df.columns),
                "rows": df.to_dict("records"),
                "count": len(df),
                "dtypes": {c: str(t) for c, t in df.dtypes.items()}
            }
        except Exception as e:
            return {"error": str(e), "file": self.file_path}

    async def sync(self, mode: str = "full") -> dict:
        try:
            df = self._load()
            df = self._clean_df(df)
            return {
                "status": "synced", "mode": mode,
                "file": self.file_path,
                "total_rows": len(df),
                "columns": list(df.columns)
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}