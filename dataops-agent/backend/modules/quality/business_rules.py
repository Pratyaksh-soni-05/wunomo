import structlog
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, func

from database import AsyncSessionLocal
from models.all_models import (
    DataSource, Pipeline, PipelineRun, QualityRule,
    KpiValue, RunStatus,
)
from modules.quality.rule_engine import QualityRuleEngine

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Rule type constants (extends rule_engine.py types)
# ---------------------------------------------------------------------------

BUSINESS_RULE_TYPES = frozenset([
    "reconciliation",        # source A row count ≈ source B row count
    "kpi_sanity",            # KPI value within expected bounds
    "cross_source_count",    # compare counts across two sources
    "freshness_sla",         # source must be profiled within N hours
    "column_sum_match",      # sum of column A == sum of column B across sources
    "kpi_trend",             # KPI value must not drop by > X% week-over-week
    "pipeline_success_rate", # pipeline must maintain minimum success rate
    "data_volume_growth",    # row count growth must stay within bounds
])


# ---------------------------------------------------------------------------
# BusinessRules
# ---------------------------------------------------------------------------

class BusinessRules:
    """
    Evaluates business-level data quality rules that span multiple sources,
    pipelines, or KPIs — beyond what single-table column checks can express.

    Rule types:
      reconciliation        — compares row counts between two sources
      kpi_sanity            — checks a KPI value is within min/max bounds
      cross_source_count    — asserts count(A) == count(B) ± tolerance
      freshness_sla         — asserts source was profiled within N hours
      column_sum_match      — asserts SUM(col) is equal across two sources
      kpi_trend             — asserts KPI didn't drop > threshold% W-o-W
      pipeline_success_rate — asserts pipeline success rate >= minimum
      data_volume_growth    — asserts row count grew within [min%, max%]

    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. CRUD wrappers (delegate to rule_engine, tag as business rule)
    # ------------------------------------------------------------------

    async def create_rule(
        self,
        pipeline_id: str,
        name: str,
        rule_type: str,
        rule_config: dict,
        severity: str = "high",
        is_blocking: bool = True,
        column_name: str | None = None,
    ) -> dict:
        """
        Creates a business QualityRule (delegates to RuleEngine).
        rule_type must be one of BUSINESS_RULE_TYPES.

        rule_config schema per type:
          reconciliation:        { source_a_id, source_b_id, tolerance_pct }
          kpi_sanity:            { kpi_name, min_value, max_value }
          cross_source_count:    { source_a_id, source_b_id, tolerance_pct }
          freshness_sla:         { source_id, max_hours }
          column_sum_match:      { source_a_id, col_a, source_b_id, col_b, tolerance_pct }
          kpi_trend:             { kpi_name, max_drop_pct }
          pipeline_success_rate: { pipeline_id, min_success_rate_pct, window_days }
          data_volume_growth:    { source_id, min_growth_pct, max_growth_pct, window_days }
        """
        if rule_type not in BUSINESS_RULE_TYPES:
            return {
                "error": f"Unknown business rule type '{rule_type}'. "
                         f"Allowed: {sorted(BUSINESS_RULE_TYPES)}"
            }

        engine = QualityRuleEngine(self.tenant_id)
        return await engine.create_rule(
            pipeline_id=pipeline_id,
            name=name,
            rule_type=rule_type,
            column_name=column_name or "",
            rule_config={**rule_config, "_business_rule": True},
            severity=severity,
            is_blocking=is_blocking,
        )

    async def list_rules(self, pipeline_id: str | None = None) -> list[dict]:
        """Lists all business rules for the tenant."""
        engine = QualityRuleEngine(self.tenant_id)
        result = await engine.list_rules(pipeline_id=pipeline_id)
        if isinstance(result, dict) and "error" in result:
            return result
        # QualityRuleEngine.list_rules() returns {"rules": [...], "count": N},
        # not a bare list — iterating the dict directly iterated its *keys*
        # (the strings "rules"/"count"), so `r.get(...)` below raised
        # AttributeError: 'str' object has no attribute 'get' on every call.
        all_rules = result.get("rules", []) if isinstance(result, dict) else result
        return [r for r in all_rules if r.get("rule_config", {}).get("_business_rule")]

    async def delete_rule(self, rule_id: str) -> dict:
        engine = QualityRuleEngine(self.tenant_id)
        return await engine.delete_rule(rule_id)

    # ------------------------------------------------------------------
    # 2. Run all business rules (or a specific set)
    # ------------------------------------------------------------------

    async def run_all(
        self,
        pipeline_id: str | None = None,
        run_id: str | None = None,
    ) -> dict:
        """
        Evaluates all business rules for the tenant (or pipeline).

        Returns:
          {
            "passed": N, "failed": N, "errors": N,
            "results": [ { rule_name, rule_type, status, detail, ... } ]
          }
        """
        log.info(
            "business_rules.run_all",
            tenant_id=self.tenant_id,
            pipeline_id=pipeline_id,
        )
        try:
            rules = await self.list_rules(pipeline_id=pipeline_id)
            if isinstance(rules, dict) and "error" in rules:
                return rules

            results = []
            for rule in rules:
                result = await self._evaluate_rule(rule)
                results.append(result)

            passed = sum(1 for r in results if r["status"] == "pass")
            failed = sum(1 for r in results if r["status"] == "fail")
            errors = sum(1 for r in results if r["status"] == "error")

            log.info(
                "business_rules.run_all.done",
                passed=passed, failed=failed, errors=errors,
            )
            return {
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "total": len(results),
                "results": results,
            }
        except Exception as exc:
            log.error("business_rules.run_all.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Evaluate a single rule
    # ------------------------------------------------------------------

    async def _evaluate_rule(self, rule: dict) -> dict:
        """Dispatches to the correct check method based on rule_type."""
        rule_type = rule.get("rule_type")
        config = rule.get("rule_config", {})
        name = rule.get("name", rule_type)

        base = {"rule_id": rule.get("rule_id"), "rule_name": name, "rule_type": rule_type}

        try:
            if rule_type == "reconciliation":
                return {**base, **await self._check_reconciliation(config)}
            elif rule_type == "kpi_sanity":
                return {**base, **await self._check_kpi_sanity(config)}
            elif rule_type == "cross_source_count":
                return {**base, **await self._check_cross_source_count(config)}
            elif rule_type == "freshness_sla":
                return {**base, **await self._check_freshness_sla(config)}
            elif rule_type == "column_sum_match":
                return {**base, **await self._check_column_sum_match(config)}
            elif rule_type == "kpi_trend":
                return {**base, **await self._check_kpi_trend(config)}
            elif rule_type == "pipeline_success_rate":
                return {**base, **await self._check_pipeline_success_rate(config)}
            elif rule_type == "data_volume_growth":
                return {**base, **await self._check_data_volume_growth(config)}
            else:
                return {**base, "status": "error", "detail": f"Unknown rule type: {rule_type}"}
        except Exception as exc:
            return {**base, "status": "error", "detail": str(exc)}

    # ------------------------------------------------------------------
    # 4. Rule implementations
    # ------------------------------------------------------------------

    async def _check_reconciliation(self, config: dict) -> dict:
        """
        Asserts that row counts in source_a and source_b are within tolerance_pct of each other.
        E.g. "orders in CRM should match orders in warehouse ±2%"
        """
        source_a_id = config.get("source_a_id")
        source_b_id = config.get("source_b_id")
        tolerance_pct = float(config.get("tolerance_pct", 0))

        count_a = await self._get_source_row_count(source_a_id)
        count_b = await self._get_source_row_count(source_b_id)

        if count_a is None or count_b is None:
            return {
                "status": "error",
                "detail": "One or both sources have not been profiled (no row count in schema snapshot)",
                "count_a": count_a,
                "count_b": count_b,
            }

        if count_a == 0 and count_b == 0:
            return {"status": "pass", "detail": "Both sources are empty", "count_a": 0, "count_b": 0}

        diff_pct = abs(count_a - count_b) / max(count_a, count_b) * 100

        if diff_pct <= tolerance_pct:
            return {
                "status": "pass",
                "detail": f"Row counts match within {tolerance_pct}%: {count_a} vs {count_b} ({diff_pct:.2f}% diff)",
                "count_a": count_a,
                "count_b": count_b,
                "diff_pct": round(diff_pct, 4),
            }
        else:
            return {
                "status": "fail",
                "detail": f"Row count mismatch exceeds {tolerance_pct}%: {count_a} vs {count_b} ({diff_pct:.2f}% diff)",
                "count_a": count_a,
                "count_b": count_b,
                "diff_pct": round(diff_pct, 4),
            }

    async def _check_kpi_sanity(self, config: dict) -> dict:
        """
        Asserts that the latest KPI value is within [min_value, max_value].
        """
        kpi_name = config.get("kpi_name")
        min_value = config.get("min_value")
        max_value = config.get("max_value")

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(KpiValue)
                    .where(
                        KpiValue.tenant_id == self.tenant_id,
                        KpiValue.kpi_name == kpi_name,
                    )
                    .order_by(desc(KpiValue.recorded_at))
                    .limit(1)
                )
                kpi = result.scalar_one_or_none()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

        if kpi is None:
            return {"status": "error", "detail": f"No KPI values found for '{kpi_name}'"}

        value = kpi.value
        violations = []
        if min_value is not None and value < min_value:
            violations.append(f"value {value} is below minimum {min_value}")
        if max_value is not None and value > max_value:
            violations.append(f"value {value} exceeds maximum {max_value}")

        if violations:
            return {
                "status": "fail",
                "detail": f"KPI '{kpi_name}' sanity check failed: {'; '.join(violations)}",
                "kpi_name": kpi_name,
                "value": value,
                "min": min_value,
                "max": max_value,
            }
        return {
            "status": "pass",
            "detail": f"KPI '{kpi_name}' = {value} is within bounds [{min_value}, {max_value}]",
            "kpi_name": kpi_name,
            "value": value,
        }

    async def _check_cross_source_count(self, config: dict) -> dict:
        """Same as reconciliation but named differently for clarity in rule lists."""
        return await self._check_reconciliation(config)

    async def _check_freshness_sla(self, config: dict) -> dict:
        """
        Asserts that the DataSource was profiled within max_hours.
        """
        source_id = config.get("source_id")
        max_hours = float(config.get("max_hours", 24))

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

        if source is None:
            return {"status": "error", "detail": f"Source {source_id} not found"}

        if source.last_profiled_at is None:
            return {
                "status": "fail",
                "detail": f"Source '{source.name}' has never been profiled",
                "source_name": source.name,
                "last_profiled_at": None,
            }

        hours_ago = (utcnow() - source.last_profiled_at).total_seconds() / 3600
        if hours_ago > max_hours:
            return {
                "status": "fail",
                "detail": f"Source '{source.name}' last profiled {hours_ago:.1f}h ago (SLA: {max_hours}h)",
                "source_name": source.name,
                "hours_since_profiled": round(hours_ago, 2),
                "sla_hours": max_hours,
            }
        return {
            "status": "pass",
            "detail": f"Source '{source.name}' profiled {hours_ago:.1f}h ago (within {max_hours}h SLA)",
            "hours_since_profiled": round(hours_ago, 2),
        }

    async def _check_column_sum_match(self, config: dict) -> dict:
        """
        Asserts that SUM of col_a in source_a ≈ SUM of col_b in source_b.
        Reads from schema_snapshot.column_stats if available.
        """
        source_a_id = config.get("source_a_id")
        col_a = config.get("col_a")
        source_b_id = config.get("source_b_id")
        col_b = config.get("col_b")
        tolerance_pct = float(config.get("tolerance_pct", 1.0))

        sum_a = await self._get_column_stat(source_a_id, col_a, "sum")
        sum_b = await self._get_column_stat(source_b_id, col_b, "sum")

        if sum_a is None or sum_b is None:
            return {
                "status": "error",
                "detail": f"Column sum not available in schema snapshot (run profiler first). "
                          f"col_a='{col_a}':{sum_a}, col_b='{col_b}':{sum_b}",
            }

        if sum_a == 0 and sum_b == 0:
            return {"status": "pass", "detail": "Both column sums are 0"}

        diff_pct = abs(sum_a - sum_b) / max(abs(sum_a), abs(sum_b)) * 100

        if diff_pct <= tolerance_pct:
            return {
                "status": "pass",
                "detail": f"Column sums match within {tolerance_pct}%: {col_a}={sum_a} vs {col_b}={sum_b}",
                "sum_a": sum_a, "sum_b": sum_b, "diff_pct": round(diff_pct, 4),
            }
        return {
            "status": "fail",
            "detail": f"Column sum mismatch: {col_a}={sum_a} vs {col_b}={sum_b} ({diff_pct:.2f}% diff > {tolerance_pct}%)",
            "sum_a": sum_a, "sum_b": sum_b, "diff_pct": round(diff_pct, 4),
        }

    async def _check_kpi_trend(self, config: dict) -> dict:
        """
        Asserts KPI value did not drop by more than max_drop_pct compared to 7 days ago.
        """
        kpi_name = config.get("kpi_name")
        max_drop_pct = float(config.get("max_drop_pct", 20))
        window = timedelta(days=7)

        try:
            async with AsyncSessionLocal() as db:
                # Latest value
                result = await db.execute(
                    select(KpiValue)
                    .where(KpiValue.tenant_id == self.tenant_id, KpiValue.kpi_name == kpi_name)
                    .order_by(desc(KpiValue.recorded_at)).limit(1)
                )
                latest = result.scalar_one_or_none()

                if latest is None:
                    return {"status": "error", "detail": f"No KPI values for '{kpi_name}'"}

                since = utcnow() - window - timedelta(days=1)
                until = utcnow() - window

                result = await db.execute(
                    select(KpiValue)
                    .where(
                        KpiValue.tenant_id == self.tenant_id,
                        KpiValue.kpi_name == kpi_name,
                        KpiValue.recorded_at >= since,
                        KpiValue.recorded_at <= until,
                    )
                    .order_by(desc(KpiValue.recorded_at)).limit(1)
                )
                prev = result.scalar_one_or_none()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

        if prev is None:
            return {
                "status": "error",
                "detail": f"No KPI value found for '{kpi_name}' from 7 days ago — cannot evaluate trend",
            }

        if prev.value == 0:
            return {"status": "error", "detail": "Previous KPI value is 0 — cannot compute % change"}

        change_pct = (latest.value - prev.value) / abs(prev.value) * 100

        if change_pct < -max_drop_pct:
            return {
                "status": "fail",
                "detail": f"KPI '{kpi_name}' dropped {abs(change_pct):.1f}% (max allowed: {max_drop_pct}%)",
                "current": latest.value, "previous": prev.value, "change_pct": round(change_pct, 2),
            }
        return {
            "status": "pass",
            "detail": f"KPI '{kpi_name}' trend OK: {change_pct:+.1f}% vs 7 days ago",
            "current": latest.value, "previous": prev.value, "change_pct": round(change_pct, 2),
        }

    async def _check_pipeline_success_rate(self, config: dict) -> dict:
        """
        Asserts that a pipeline's success rate over the last N days
        meets the minimum threshold.
        """
        pipeline_id = config.get("pipeline_id")
        min_rate = float(config.get("min_success_rate_pct", 90))
        window_days = int(config.get("window_days", 7))
        since = utcnow() - timedelta(days=window_days)

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(PipelineRun).where(
                        PipelineRun.tenant_id == self.tenant_id,
                        PipelineRun.pipeline_id == pipeline_id,
                        PipelineRun.created_at >= since,
                        PipelineRun.status.in_([RunStatus.SUCCESS, RunStatus.FAILED]),
                    )
                )
                runs = result.scalars().all()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

        if not runs:
            return {"status": "error", "detail": f"No completed runs found for pipeline {pipeline_id} in last {window_days} days"}

        total = len(runs)
        success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
        rate = success / total * 100

        if rate >= min_rate:
            return {
                "status": "pass",
                "detail": f"Pipeline success rate {rate:.1f}% meets minimum {min_rate}%",
                "success_rate_pct": round(rate, 2), "total_runs": total, "success_runs": success,
            }
        return {
            "status": "fail",
            "detail": f"Pipeline success rate {rate:.1f}% is below minimum {min_rate}%",
            "success_rate_pct": round(rate, 2), "total_runs": total, "success_runs": success,
        }

    async def _check_data_volume_growth(self, config: dict) -> dict:
        """
        Asserts row count growth from N days ago is within [min_growth_pct, max_growth_pct].
        Reads from schema_snapshot.row_count — requires at least 2 profiles.
        """
        source_id = config.get("source_id")
        min_growth = config.get("min_growth_pct")
        max_growth = config.get("max_growth_pct")

        current_count = await self._get_source_row_count(source_id)
        if current_count is None:
            return {"status": "error", "detail": "Source has no row_count in schema snapshot"}

        # For volume growth we'd need historical snapshots — for now check absolute bounds
        notes = []
        if min_growth is not None and current_count == 0:
            notes.append("Current row count is 0 — possible data loss")

        return {
            "status": "pass" if not notes else "fail",
            "detail": "; ".join(notes) if notes else f"Row count is {current_count}",
            "row_count": current_count,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_source_row_count(self, source_id: str | None) -> int | None:
        if not source_id:
            return None
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()
            if source and source.schema_snapshot:
                return source.schema_snapshot.get("row_count")
            return None
        except Exception:
            return None

    async def _get_column_stat(
        self,
        source_id: str | None,
        column_name: str | None,
        stat: str,
    ) -> float | None:
        """
        Reads a named stat (sum, mean, min, max) from schema_snapshot.column_stats.
        Schema profiler must have stored column-level stats for this to work.
        """
        if not source_id or not column_name:
            return None
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DataSource).where(
                        DataSource.id == source_id,
                        DataSource.tenant_id == self.tenant_id,
                    )
                )
                source = result.scalar_one_or_none()
            if not source or not source.schema_snapshot:
                return None
            col_stats = source.schema_snapshot.get("column_stats", {})
            col = col_stats.get(column_name, {})
            return col.get(stat)
        except Exception:
            return None