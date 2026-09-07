import ast
import io
import time
import traceback
import structlog
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Any

from database import AsyncSessionLocal
from models.all_models import DataSource
from modules.governance.audit_trail import AuditTrail
from modules.transformation import python_guard, python_sandbox
from services.tenant_context import tenant_scoped

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

MAX_ROWS_INPUT = 500_000     # max rows loaded into runner
MAX_ROWS_OUTPUT = 100_000    # max rows in result_df

# The static allowlist and the execution sandbox now live in their own
# modules. See python_guard.py for what code is rejected before it runs (and
# why the previous check let all 14 battery payloads execute), and
# python_sandbox.py for the process isolation and resource limits that bound
# what still gets through.
EXECUTION_TIMEOUT_SECS = python_sandbox.EXECUTION_TIMEOUT_SECS
MAX_CODE_LENGTH = python_guard.MAX_CODE_LENGTH


# ---------------------------------------------------------------------------
# PythonRunner
# ---------------------------------------------------------------------------

@tenant_scoped
class PythonRunner:
    """
    Executes Pandas transformation code in a restricted Python environment.

    Isolation approach (isolated child process):
      1. Static guard — rejects private/dunder access anywhere in the tree,
         the pandas/numpy I/O surface, and imports outside the allowlist
         (python_guard.py)
      2. Forked child process with dropped resources — memory, CPU, a
         zero-byte file-size limit and a cleared environment
         (python_sandbox.py)
      3. Wall-clock timeout enforced by KILLING the child, which the previous
         thread-based timeout could not do
      4. Row caps on input and output DataFrames
      5. Audit trail for every execution

    Note: the previous version of this docstring claimed the in-process
    sandbox was "sufficient" for LLM-generated code. It was not: a 14-payload
    battery executed 14 of 14 against it, recovering os, the JWT secret, the
    admin database URL and the credential encryption key. Layers 1-3 above
    replaced it.

    The remaining caveat is real and narrower. The child shares the host's
    filesystem and network namespace, so code that defeats layer 1 can still
    read a world-readable file or open a socket. For genuinely untrusted code,
    deploy in a gVisor/Firecracker microVM.

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Run code against a DataSource (loads data automatically)
    # ------------------------------------------------------------------

    async def run_on_source(
        self,
        source_id: str,
        code: str,
        row_limit: int = MAX_ROWS_INPUT,
        actor: str = "agent",
    ) -> dict:
        """
        Loads a DataSource into a DataFrame and executes the transformation code.

        Steps:
          1. Load source data via connector (CSV/Excel/JSON/Postgres/MySQL)
          2. Safety-check the code via AST
          3. Execute in restricted namespace
          4. Return result_df rows + metadata

        Args:
            source_id:  UUID of the DataSource
            code:       Pandas code string (input: `df`, output: `result_df`)
            row_limit:  max input rows loaded
            actor:      for audit trail

        Returns:
          {
            "rows": [...], "columns": [...], "row_count": N,
            "truncated": bool, "duration_ms": N,
            "source_id": ..., "warnings": [...]
          }
        """
        log.info(
            "python_runner.run_on_source",
            tenant_id=self.tenant_id,
            source_id=source_id,
        )

        # 1. Safety check
        safety = self._ast_check(code)
        if "error" in safety:
            return safety

        # 2. Load data
        df_result = await self._load_dataframe(source_id, row_limit)
        if "error" in df_result:
            return df_result
        df = df_result["df"]

        # 3. Execute
        exec_result = self._execute(code, df)
        if "error" in exec_result:
            return exec_result

        result_df = exec_result["result_df"]
        duration_ms = exec_result["duration_ms"]
        warnings = exec_result.get("warnings", [])

        # 4. Cap output rows
        truncated = len(result_df) > MAX_ROWS_OUTPUT
        result_df = result_df.head(MAX_ROWS_OUTPUT)

        # 5. Serialize
        rows = self._serialize_df(result_df)
        columns = list(result_df.columns)

        # 6. Audit
        await AuditTrail(self.tenant_id).log_action(
            actor=actor,
            action="pandas.executed",
            resource_type="source",
            resource_id=source_id,
            payload={
                "row_count_in": len(df),
                "row_count_out": len(rows),
                "duration_ms": duration_ms,
                "truncated": truncated,
            },
        )

        log.info(
            "python_runner.run_on_source.done",
            rows_in=len(df),
            rows_out=len(rows),
            duration_ms=duration_ms,
        )

        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "truncated": truncated,
            "duration_ms": duration_ms,
            "source_id": source_id,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # 2. Run code against an in-memory DataFrame
    # ------------------------------------------------------------------

    async def run_on_dataframe(
        self,
        df: pd.DataFrame,
        code: str,
    ) -> dict:
        """
        Runs Pandas transformation code against a DataFrame passed directly.
        Used by quality checks and pipeline run steps that already have data in memory.

        Returns: same schema as run_on_source
        """
        log.info("python_runner.run_on_dataframe", rows=len(df))

        safety = self._ast_check(code)
        if "error" in safety:
            return safety

        # Cap input
        df_capped = df.head(MAX_ROWS_INPUT)
        exec_result = self._execute(code, df_capped)
        if "error" in exec_result:
            return exec_result

        result_df = exec_result["result_df"]
        truncated = len(result_df) > MAX_ROWS_OUTPUT
        result_df = result_df.head(MAX_ROWS_OUTPUT)
        rows = self._serialize_df(result_df)

        return {
            "rows": rows,
            "columns": list(result_df.columns),
            "row_count": len(rows),
            "truncated": truncated,
            "duration_ms": exec_result["duration_ms"],
            "warnings": exec_result.get("warnings", []),
        }

    # ------------------------------------------------------------------
    # 3. Preview (first 100 rows, no audit)
    # ------------------------------------------------------------------

    async def preview(self, source_id: str, code: str) -> dict:
        """
        Runs a transformation and returns only the first 100 rows.
        Used for interactive preview in the chat agent before committing to a full run.
        Does NOT write to the audit trail.
        """
        result = await self.run_on_source(source_id, code, row_limit=100)
        if "error" in result:
            return result
        return {
            "rows": result["rows"][:100],
            "columns": result["columns"],
            "row_count": min(result["row_count"], 100),
            "preview": True,
        }

    # ------------------------------------------------------------------
    # Internal: AST safety check
    # ------------------------------------------------------------------

    def _ast_check(self, code: str) -> dict:
        """Static validation. See modules/transformation/python_guard.py for
        what is rejected and why the previous one-level attribute check was
        structurally unable to see a sandbox escape."""
        verdict = python_guard.validate(code)
        if not verdict.ok:
            return {"error": verdict.error}
        return {"ok": True}

    # ------------------------------------------------------------------
    # Internal: restricted exec
    # ------------------------------------------------------------------

    def _execute(self, code: str, df: pd.DataFrame) -> dict:
        """Executes the transformation in an isolated, resource-limited child
        process. See modules/transformation/python_sandbox.py.

        The previous implementation ran the code in a daemon thread and called
        join(timeout). That reported a timeout without stopping anything —
        measured: the call returned at 1.01s under a 1s timeout while the
        thread kept running. Python cannot kill a thread, so this had to
        change mechanism rather than parameters.
        """
        start = time.monotonic()
        result = python_sandbox.run_sandboxed(code, df.copy(), EXECUTION_TIMEOUT_SECS)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        if "error" in result:
            detail = result.get("detail")
            if detail:
                # Kept out of the response on purpose: a traceback from inside
                # the sandbox carries absolute paths, module names and local
                # values back to whatever is iterating against it.
                log.warning(
                    "python_runner.sandbox_failure",
                    tenant_id=self.tenant_id,
                    detail=detail,
                )
            return {"error": result["error"]}

        result_df = result["result_df"]

        warnings = []
        if result_df.empty:
            warnings.append("result_df is empty — transformation returned 0 rows")

        return {
            "result_df": result_df,
            "duration_ms": duration_ms,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Internal: load DataFrame from source
    # ------------------------------------------------------------------

    async def _load_dataframe(self, source_id: str, row_limit: int) -> dict:
        """
        Loads a DataSource into a pandas DataFrame using the existing connectors.
        Supports: csv, excel, json, postgres, mysql.
        """
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select as sa_select
                result = await db.execute(
                    sa_select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()

            if source is None:
                return {"error": f"DataSource {source_id} not found"}

            source_type = (
                source.source_type.value
                if hasattr(source.source_type, "value")
                else str(source.source_type)
            )
            config = source.connection_config or {}

            if source_type in ("csv", "excel", "json"):
                from modules.ingestion.connectors.file_connector import FileConnector
                connector = FileConnector(config, source_type)
                result = await connector.preview(limit=row_limit)
                if "error" in result:
                    return result
                df = pd.DataFrame(result.get("rows", []), columns=result.get("columns") or None)
            elif source_type == "postgres":
                import asyncpg
                host = config.get("host", "localhost")
                port = int(config.get("port", 5432))
                database = config.get("database", "")
                user = config.get("username", config.get("user", ""))
                password = config.get("password", "")
                table = config.get("table", config.get("default_table", ""))
                if not table:
                    return {"error": "Postgres source has no 'table' specified in connection_config"}
                conn = await asyncpg.connect(
                    host=host, port=port, database=database,
                    user=user, password=password, timeout=30,
                )
                try:
                    rows_raw = await conn.fetch(f'SELECT * FROM {table} LIMIT {row_limit}')
                    columns = list(rows_raw[0].keys()) if rows_raw else []
                    df = pd.DataFrame([dict(r) for r in rows_raw], columns=columns)
                finally:
                    await conn.close()
            elif source_type == "mysql":
                from modules.ingestion.connectors.mysql_connector import MySQLConnector
                table = config.get("table", config.get("default_table", ""))
                if not table:
                    return {"error": "MySQL source has no 'table' specified in connection_config"}
                connector = MySQLConnector(config)
                result = await connector.preview(table, limit=row_limit)
                df = pd.DataFrame(result.get("rows", []), columns=result.get("columns") or None)
            else:
                return {"error": f"PythonRunner does not support source type '{source_type}'"}

            if isinstance(df, dict) and "error" in df:
                return df

            return {"df": df}

        except Exception as exc:
            log.error("python_runner._load_dataframe.error", error=str(exc))
            return {"error": f"Failed to load source data: {str(exc)}"}

    # ------------------------------------------------------------------
    # Internal: serialize DataFrame to JSON-safe list of dicts
    # ------------------------------------------------------------------

    def _serialize_df(self, df: pd.DataFrame) -> list[dict]:
        """
        Converts a DataFrame to a list of dicts with JSON-safe values.
        Handles: NaN → None, Timestamp → ISO string, numpy types → native Python.
        """
        records = []
        for _, row in df.iterrows():
            record = {}
            for col, val in row.items():
                if pd.isna(val) if not isinstance(val, (list, dict)) else False:
                    record[col] = None
                elif isinstance(val, pd.Timestamp):
                    record[col] = val.isoformat()
                elif isinstance(val, (np.integer,)):
                    record[col] = int(val)
                elif isinstance(val, (np.floating,)):
                    record[col] = float(val)
                elif isinstance(val, (np.bool_,)):
                    record[col] = bool(val)
                else:
                    record[col] = val
            records.append(record)
        return records