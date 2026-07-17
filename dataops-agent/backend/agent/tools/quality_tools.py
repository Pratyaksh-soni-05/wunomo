from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result


@tool
async def run_quality_checks(tenant_id: str, pipeline_id: str, run_id: Optional[str] = None) -> dict:
    """Run all active quality rules for a pipeline. Returns pass/fail per rule + quality score."""
    from modules.quality.rule_engine import QualityRuleEngine
    return cap_tool_result(await QualityRuleEngine(tenant_id).run_checks(pipeline_id))


@tool
async def create_quality_rule(
    tenant_id: str,
    pipeline_id: str,
    name: str,
    rule_type: str,
    column_name: Optional[str] = None,
    rule_config: dict = None,
    severity: str = "high",
    is_blocking: bool = True
) -> dict:
    """Create a quality rule. rule_type: not_null|unique|accepted_values|range|freshness|regex|row_count|custom_sql.
    `name` is required — give the rule a short, descriptive name."""
    from modules.quality.rule_engine import QualityRuleEngine
    return await QualityRuleEngine(tenant_id).create_rule(
        pipeline_id=pipeline_id, name=name, rule_type=rule_type,
        column_name=column_name, rule_config=rule_config or {},
        severity=severity, is_blocking=is_blocking,
    )


@tool
async def get_quality_report(tenant_id: str, pipeline_id: str) -> dict:
    """Get the quality rules configured for a pipeline, with each rule's pass/fail
    counts so far — the closest real substitute for a "quality report"."""
    from modules.quality.rule_engine import QualityRuleEngine
    return cap_tool_result(await QualityRuleEngine(tenant_id).list_rules(pipeline_id))


@tool
async def validate_business_rule(tenant_id: str, pipeline_id: str) -> dict:
    """Run all business validation rules configured for a pipeline (reconciliation,
    KPI sanity, cross-source counts, freshness SLA, etc.) and return every result.
    Business rules apply per-pipeline, not per-dataset — there is no way to run a
    single named rule against an arbitrary dataset in isolation."""
    from modules.quality.business_rules import BusinessRules
    return cap_tool_result(await BusinessRules(tenant_id).run_all(pipeline_id))


@tool
async def list_business_rules(tenant_id: str, pipeline_id: Optional[str] = None) -> dict:
    """List all configured business validation rules for the tenant, optionally
    filtered to one pipeline."""
    from modules.quality.business_rules import BusinessRules
    rules = await BusinessRules(tenant_id).list_rules(pipeline_id)
    if isinstance(rules, dict) and "error" in rules:
        return rules
    return {"rules": rules, "count": len(rules)}


quality_tools = [run_quality_checks, create_quality_rule, get_quality_report,
                 validate_business_rule, list_business_rules]
