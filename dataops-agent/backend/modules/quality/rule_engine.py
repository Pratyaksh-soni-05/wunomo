import uuid
from datetime import datetime, timezone
from sqlalchemy import select
import structlog

from database import AsyncSessionLocal
from models.all_models import QualityRule, Pipeline

log = structlog.get_logger()

def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)

RULE_TYPES = [
    "not_null", "unique", "accepted_values", "range",
    "freshness", "regex", "row_count", "custom_sql"
]


class QualityRuleEngine:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ── CRUD ──────────────────────────────────────────────────────────────────
    async def create_rule(
        self, pipeline_id: str, name: str, rule_type: str,
        column_name: str = None, rule_config: dict = None,
        severity: str = "high", is_blocking: bool = True
    ) -> dict:
        if rule_type not in RULE_TYPES:
            return {"error": f"Unknown rule_type '{rule_type}'. Valid: {RULE_TYPES}"}
        async with AsyncSessionLocal() as db:
            rule = QualityRule(
                id=str(uuid.uuid4()),
                pipeline_id=pipeline_id,
                tenant_id=self.tenant_id,
                name=name,
                rule_type=rule_type,
                column_name=column_name,
                rule_config=rule_config or {},
                severity=severity,
                is_blocking=is_blocking,
                is_active=True,
                created_at=utcnow()
            )
            db.add(rule)
            await db.commit()
            await db.refresh(rule)
            log.info("quality_rule_created", rule_id=rule.id, type=rule_type)
            return {"id": rule.id, "name": rule.name,
                    "rule_type": rule.rule_type, "status": "created"}

    async def list_rules(self, pipeline_id: str = None) -> dict:
        async with AsyncSessionLocal() as db:
            q = select(QualityRule).where(QualityRule.tenant_id == self.tenant_id)
            if pipeline_id:
                q = q.where(QualityRule.pipeline_id == pipeline_id)
            r = await db.execute(q)
            rules = r.scalars().all()
            return {
                "rules": [
                    {
                        "id": rule.id, "name": rule.name,
                        "pipeline_id": rule.pipeline_id,
                        "rule_type": rule.rule_type,
                        "column_name": rule.column_name,
                        "rule_config": rule.rule_config,
                        "severity": rule.severity,
                        "is_blocking": rule.is_blocking,
                        "is_active": rule.is_active,
                        "pass_count": rule.pass_count,
                        "fail_count": rule.fail_count
                    }
                    for rule in rules
                ],
                "count": len(rules)
            }

    async def delete_rule(self, rule_id: str) -> dict:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(QualityRule).where(
                QualityRule.id == rule_id,
                QualityRule.tenant_id == self.tenant_id
            ))
            rule = r.scalars().first()
            if not rule:
                return {"error": "Rule not found"}
            await db.delete(rule)
            await db.commit()
            return {"message": "Rule deleted", "id": rule_id}

    # ── RUN CHECKS ────────────────────────────────────────────────────────────
    async def run_checks(self, pipeline_id: str) -> dict:
        async with AsyncSessionLocal() as db:
            p = await db.execute(select(Pipeline).where(
                Pipeline.id == pipeline_id,
                Pipeline.tenant_id == self.tenant_id,
            ))
            if p.scalar_one_or_none() is None:
                return {"error": f"Pipeline {pipeline_id} not found"}
            r = await db.execute(select(QualityRule).where(
                QualityRule.pipeline_id == pipeline_id,
                QualityRule.tenant_id == self.tenant_id,
                QualityRule.is_active == True
            ))
            rules = r.scalars().all()
            if not rules:
                return {"pipeline_id": pipeline_id, "score": 100.0,
                        "passed": 0, "failed": 0, "results": [],
                        "message": "No active quality rules"}

            results, passed, failed, blocking_fail = [], 0, 0, False

            for rule in rules:
                result = await self._evaluate_rule(rule, pipeline_id, db)
                if result["passed"]:
                    passed += 1
                    rule.pass_count = (rule.pass_count or 0) + 1
                else:
                    failed += 1
                    rule.fail_count = (rule.fail_count or 0) + 1
                    if rule.is_blocking:
                        blocking_fail = True
                results.append(result)

            await db.commit()

            total = passed + failed
            score = round((passed / total) * 100, 2) if total > 0 else 100.0

            return {
                "pipeline_id": pipeline_id,
                "score": score,
                "passed": passed,
                "failed": failed,
                "total_rules": total,
                "blocking_failure": blocking_fail,
                "results": results
            }

    async def _evaluate_rule(self, rule: QualityRule,
                              pipeline_id: str, db) -> dict:
        """
        Evaluate one quality rule. For file/DB sources this runs
        the check against the source data via the connector.
        """
        base = {
            "rule_id":     rule.id,
            "rule_name":   rule.name,
            "rule_type":   rule.rule_type,
            "column":      rule.column_name,
            "severity":    rule.severity,
            "is_blocking": rule.is_blocking,
        }
        try:
            result = await self._run_rule_logic(rule, pipeline_id, db)
            return {**base, **result}
        except Exception as e:
            return {**base, "passed": False,
                    "message": f"Rule evaluation error: {str(e)}"}

    async def _run_rule_logic(self, rule: QualityRule,
                               pipeline_id: str, db) -> dict:
        from sqlalchemy import select as sa_select
        from models.all_models import Pipeline, DataSource

        # Get pipeline → source
        p = await db.get(Pipeline, pipeline_id)
        if not p or not p.source_id:
            return {"passed": True, "message": "No source attached — skipping"}

        source = await db.get(DataSource, p.source_id)
        if not source:
            return {"passed": True, "message": "Source not found — skipping"}

        from modules.ingestion.connector_manager import ConnectorManager
        connector = ConnectorManager(self.tenant_id)._get_connector(source)

        # File sources ignore this (single implicit table); DB sources need
        # the actual table name from the source's own connection_config.
        table_name = (source.connection_config or {}).get("table", "main")

        rt  = rule.rule_type
        col = rule.column_name
        cfg = rule.rule_config or {}

        # ── row_count check (no column needed) ────────────────────────────────
        if rt == "row_count":
            preview = await connector.preview(table_name, limit=10000)
            count   = preview.get("count", 0)
            min_r   = cfg.get("min_rows", 1)
            passed  = count >= min_r
            return {"passed": passed,
                    "message": f"Row count {count} {'≥' if passed else '<'} min {min_r}"}

        # ── column-level checks ────────────────────────────────────────────────
        if not col:
            return {"passed": True, "message": "No column specified — skipping"}

        preview = await connector.preview(table_name, limit=10000)
        rows    = preview.get("rows", [])
        if not rows:
            return {"passed": True, "message": "No data to check"}

        import pandas as pd
        df  = pd.DataFrame(rows)
        if col not in df.columns:
            return {"passed": False,
                    "message": f"Column '{col}' not found in data"}

        series = df[col]

        if rt == "not_null":
            null_count = int(series.isnull().sum())
            passed = null_count == 0
            return {"passed": passed,
                    "message": f"{null_count} null values in '{col}'"}

        if rt == "unique":
            dupes = int(series.duplicated().sum())
            passed = dupes == 0
            return {"passed": passed,
                    "message": f"{dupes} duplicate values in '{col}'"}

        if rt == "accepted_values":
            accepted = cfg.get("values", [])
            bad = series.dropna()[~series.dropna().isin(accepted)]
            passed = len(bad) == 0
            return {"passed": passed,
                    "message": f"{len(bad)} values not in accepted list {accepted}"}

        if rt == "range":
            mn, mx = cfg.get("min"), cfg.get("max")
            numeric = pd.to_numeric(series, errors="coerce")
            out = numeric.dropna()
            violations = 0
            if mn is not None: violations += int((out < mn).sum())
            if mx is not None: violations += int((out > mx).sum())
            passed = violations == 0
            return {"passed": passed,
                    "message": f"{violations} values outside range [{mn}, {mx}]"}

        if rt == "regex":
            pattern = cfg.get("pattern", ".*")
            matches = series.dropna().astype(str).str.match(pattern)
            fails   = int((~matches).sum())
            passed  = fails == 0
            return {"passed": passed,
                    "message": f"{fails} values don't match pattern '{pattern}'"}

        if rt == "custom_sql":
            sql = cfg.get("sql", "")
            if not sql:
                return {"passed": True, "message": "custom_sql skipped — no SQL configured"}
            source_type_val = (
                source.source_type.value if hasattr(source.source_type, "value")
                else str(source.source_type)
            )
            if source_type_val not in ("postgres", "mysql"):
                return {"passed": True, "message": "custom_sql skipped — not a SQL source"}
            # Routed through SqlRunner's safety layer (keyword blocklist +
            # SELECT/WITH-only + row cap + audit log) instead of calling the
            # connector's raw execute_sql() directly — that call had zero
            # sandboxing, letting anyone with quality.manage configure a
            # "quality rule" that ran arbitrary DDL/DML against the tenant's
            # real connected database, re-executed automatically on every
            # pipeline run. custom_sql rules are meant to return a count of
            # violation rows, which is exactly a SELECT — SqlRunner's
            # SELECT-only restriction doesn't lose any real capability here.
            from modules.transformation.sql_runner import SqlRunner
            result = await SqlRunner(self.tenant_id).run_on_source(
                source.id, sql, actor="quality_rule"
            )
            if "error" in result:
                return {"passed": False, "message": f"Custom SQL rejected: {result['error']}"}
            count  = result.get("row_count", 0)
            passed = count == 0   # convention: SQL returns violation rows
            return {"passed": passed,
                    "message": f"Custom SQL returned {count} violation row(s)"}

        return {"passed": True, "message": f"Rule type '{rt}' not yet implemented"}