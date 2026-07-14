from langchain_core.tools import tool
from typing import Optional
from agent.tools._utils import cap_tool_result


@tool
async def run_quality_checks(tenant_id: str, pipeline_id: str, run_id: Optional[str] = None) -> dict:
    """Run all active quality rules for a pipeline. Returns pass/fail per rule + quality score."""
    from modules.quality.test_runner import QualityTestRunner
    return cap_tool_result(await QualityTestRunner(tenant_id, pipeline_id).run_all(run_id))


@tool
async def create_quality_rule(
    tenant_id: str,
    pipeline_id: str,
    rule_type: str,
    column_name: Optional[str] = None,
    rule_config: dict = None,
    severity: str = "high",
    is_blocking: bool = True
) -> dict:
    """Create a quality rule. rule_type: not_null|unique|accepted_values|range|freshness|regex|row_count|custom_sql."""
    from modules.quality.rule_engine import RuleEngine
    return await RuleEngine(tenant_id).create_rule(
        pipeline_id, rule_type, column_name, rule_config or {}, severity, is_blocking
    )


@tool
async def get_quality_report(tenant_id: str, pipeline_id: str) -> dict:
    """Get the quality report for a pipeline with pass/fail stats and trend data."""
    from modules.quality.rule_engine import RuleEngine
    return cap_tool_result(await RuleEngine(tenant_id).get_report(pipeline_id))


@tool
async def validate_business_rule(tenant_id: str, rule_name: str, dataset_id: str) -> dict:
    """Run a named business rule: reconciliation_match|revenue_consistency|duplicate_detection|kpi_sanity_check."""
    from modules.quality.business_rules import BusinessRuleLibrary
    return cap_tool_result(await BusinessRuleLibrary(tenant_id).run(rule_name, dataset_id))


@tool
async def list_business_rules(tenant_id: str) -> dict:
    """List all available built-in business validation rules."""
    from modules.quality.business_rules import BusinessRuleLibrary
    return BusinessRuleLibrary(tenant_id).list_rules()


quality_tools = [run_quality_checks, create_quality_rule, get_quality_report,
                 validate_business_rule, list_business_rules]