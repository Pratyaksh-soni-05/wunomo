import re
import structlog
from datetime import datetime, timezone
from sqlalchemy import select
from langchain_core.messages import SystemMessage, HumanMessage

from database import AsyncSessionLocal
from models.all_models import DataSource, Pipeline
from services.llm_service import invoke_llm

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_SQL_SYSTEM_PROMPT = """You are an expert SQL engineer working inside AXIOM, an AI DataOps platform.
Your job is to generate safe, production-grade SQL transformation queries.

Rules you MUST follow:
1. Never use DROP, TRUNCATE, DELETE, or ALTER TABLE in generated SQL.
2. Never use DDL statements (CREATE TABLE, etc.) unless the user explicitly asks for a staging table.
3. Always qualify column names with table aliases to avoid ambiguity.
4. Use CTEs (WITH clauses) for multi-step logic instead of deeply nested subqueries.
5. Include a LIMIT clause (default 10000) unless the user explicitly asks for full output.
6. Add inline SQL comments explaining each major step.
7. Return ONLY the SQL query — no markdown, no explanation outside the query comments.

Output format: raw SQL only, starting with -- or WITH or SELECT."""

_PANDAS_SYSTEM_PROMPT = """You are an expert Python/Pandas data engineer working inside AXIOM, an AI DataOps platform.
Your job is to generate safe, production-grade Pandas transformation code.

Rules you MUST follow:
1. The input DataFrame is always named `df`. Never rename it.
2. Never use eval(), exec(), os, subprocess, open(), or any file I/O.
3. Never import anything beyond: pandas (pd), numpy (np), re, datetime, math.
4. The final result must be assigned to `result_df` (a DataFrame).
5. Add inline comments explaining each transformation step.
6. Handle NaN values explicitly where relevant.
7. Return ONLY the Python code — no markdown fences, no prose.

Output format: raw Python code only."""

_SQL_USER_TEMPLATE = """Source schema:
{schema}

User transformation request:
{request}

Generate a SQL query that implements this transformation."""

_PANDAS_USER_TEMPLATE = """Source schema (column names and types):
{schema}

User transformation request:
{request}

Generate a Pandas transformation. Input DataFrame is `df`. Output must be `result_df`."""


class TransformGenerator:
    """
    Generates SQL or Pandas transformation code from natural language using LLM.
    Uses invoke_llm() from services.llm_service (Gemini primary, Groq fallback).
    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    async def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """Calls invoke_llm with structured messages."""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        return await invoke_llm(messages)

    async def generate_sql(
        self,
        request: str,
        source_id: str | None = None,
        pipeline_id: str | None = None,
        extra_context: str | None = None,
    ) -> dict:
        log.info("transform.generate_sql", tenant_id=self.tenant_id,
                 source_id=source_id, pipeline_id=pipeline_id)
        try:
            schema_str, resolved_source_id = await self._resolve_schema(
                source_id=source_id, pipeline_id=pipeline_id)

            user_content = _SQL_USER_TEMPLATE.format(
                schema=schema_str or "Schema not available — generate best-effort SQL.",
                request=request,
            )
            if extra_context:
                user_content += f"\n\nAdditional context: {extra_context}"

            raw_code = await self._call_llm(_SQL_SYSTEM_PROMPT, user_content)
            code = self._extract_code(raw_code, language="sql")
            warnings = self._validate_sql(code)

            log.info("transform.generate_sql.done", chars=len(code))
            return {
                "type": "sql",
                "code": code,
                "source_id": resolved_source_id,
                "schema_used": schema_str is not None,
                "generated_at": utcnow().isoformat(),
                "warnings": warnings,
            }
        except Exception as exc:
            log.error("transform.generate_sql.error", error=str(exc))
            return {"error": str(exc)}

    async def generate_pandas(
        self,
        request: str,
        source_id: str | None = None,
        pipeline_id: str | None = None,
        extra_context: str | None = None,
    ) -> dict:
        log.info("transform.generate_pandas", tenant_id=self.tenant_id,
                 source_id=source_id)
        try:
            schema_str, resolved_source_id = await self._resolve_schema(
                source_id=source_id, pipeline_id=pipeline_id)

            user_content = _PANDAS_USER_TEMPLATE.format(
                schema=schema_str or "Schema not available — use df as-is.",
                request=request,
            )
            if extra_context:
                user_content += f"\n\nAdditional context: {extra_context}"

            raw_code = await self._call_llm(_PANDAS_SYSTEM_PROMPT, user_content)
            code = self._extract_code(raw_code, language="python")
            warnings = self._validate_pandas(code)

            log.info("transform.generate_pandas.done", chars=len(code))
            return {
                "type": "pandas",
                "code": code,
                "source_id": resolved_source_id,
                "schema_used": schema_str is not None,
                "generated_at": utcnow().isoformat(),
                "warnings": warnings,
            }
        except Exception as exc:
            log.error("transform.generate_pandas.error", error=str(exc))
            return {"error": str(exc)}

    async def generate(
        self,
        request: str,
        language: str = "auto",
        source_id: str | None = None,
        pipeline_id: str | None = None,
    ) -> dict:
        if language == "auto" and source_id:
            language = await self._detect_language(source_id)
        if language == "pandas":
            return await self.generate_pandas(request, source_id=source_id,
                                              pipeline_id=pipeline_id)
        else:
            return await self.generate_sql(request, source_id=source_id,
                                           pipeline_id=pipeline_id)

    async def explain_code(self, code: str, language: str = "sql") -> dict:
        log.info("transform.explain_code", language=language)
        try:
            system = (
                "You are an expert data engineer. Explain the following "
                f"{language.upper()} code in plain English. Be concise but precise. "
                "List: what it does, what it inputs, what it outputs, and any risks."
            )
            explanation = await self._call_llm(system, f"```{language}\n{code}\n```")
            return {"explanation": explanation.strip(), "language": language}
        except Exception as exc:
            log.error("transform.explain_code.error", error=str(exc))
            return {"error": str(exc)}

    async def _resolve_schema(
        self,
        source_id: str | None,
        pipeline_id: str | None,
    ) -> tuple[str | None, str | None]:
        resolved_id = source_id

        if not resolved_id and pipeline_id:
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Pipeline).where(
                            Pipeline.id == pipeline_id,
                            Pipeline.tenant_id == self.tenant_id,
                        )
                    )
                    pipeline = result.scalar_one_or_none()
                    if pipeline:
                        resolved_id = str(pipeline.source_id)
            except Exception:
                pass

        if not resolved_id:
            return None, None

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == resolved_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()

            if source is None or not source.schema_snapshot:
                return None, resolved_id

            snapshot = source.schema_snapshot
            columns = snapshot.get("columns", [])
            if not columns:
                return None, resolved_id

            lines = [f"Table/source: {source.name} ({source.source_type.value})"]
            lines.append(f"Row count (approx): {snapshot.get('row_count', 'unknown')}")
            lines.append("Columns:")
            for col in columns:
                nullable = " (nullable)" if col.get("nullable") else ""
                lines.append(f"  - {col.get('name')}: {col.get('type')}{nullable}")

            return "\n".join(lines), resolved_id

        except Exception as exc:
            log.warning("transform._resolve_schema.error", error=str(exc))
            return None, resolved_id

    async def _detect_language(self, source_id: str) -> str:
        FILE_TYPES = {"csv", "excel", "json", "pdf", "docx", "s3"}
        SQL_TYPES = {"postgres", "mysql", "sqlite", "bigquery", "snowflake"}
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()
            if source:
                st = (source.source_type.value
                      if hasattr(source.source_type, "value")
                      else str(source.source_type))
                if st in SQL_TYPES:
                    return "sql"
                if st in FILE_TYPES:
                    return "pandas"
        except Exception:
            pass
        return "sql"

    def _extract_code(self, raw: str, language: str) -> str:
        if not raw:
            return ""
        pattern = rf"```(?:{language}|py|python|sql)?\s*\n?(.*?)```"
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return raw.strip()

    def _validate_sql(self, code: str) -> list[str]:
        warnings = []
        upper = code.upper()
        dangerous = ["DROP ", "TRUNCATE ", "DELETE ", "ALTER TABLE", "GRANT ", "REVOKE "]
        for keyword in dangerous:
            if keyword in upper:
                warnings.append(f"Dangerous keyword detected: {keyword.strip()}")
        if "LIMIT" not in upper:
            warnings.append("No LIMIT clause found — query may return unbounded rows")
        return warnings

    def _validate_pandas(self, code: str) -> list[str]:
        warnings = []
        dangerous = ["eval(", "exec(", "import os", "import sys",
                     "subprocess", "open(", "__import__"]
        for pattern in dangerous:
            if pattern in code:
                warnings.append(f"Dangerous pattern detected: {pattern}")
        if "result_df" not in code:
            warnings.append("Code does not assign output to `result_df`")
        return warnings