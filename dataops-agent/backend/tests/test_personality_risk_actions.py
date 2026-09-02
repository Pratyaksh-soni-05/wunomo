"""Regression guard for the "phantom high-risk tools" bug: every name in
RISK_ACTIONS must be a real, currently-registered agent tool, or
requires_approval() silently never blocks it in any operation mode. This
is exactly how delete_records/drop_table/modify_schema/revoke_access/
rerun_pipeline/modify_business_rule/update_contract/publish_output/
run_quality_check/list_sources/generate_report went unnoticed -- see
CLAUDE.md's "Phantom high-risk tools" Known-broken row.
"""
from agent.personality import RISK_ACTIONS, get_risk_level, build_system_prompt, SYSTEM_PROMPTS
from agent.tools import ALL_TOOLS
from models.all_models import PersonalityMode, OperationMode

REAL_TOOL_NAMES = {t.name for t in ALL_TOOLS}


def test_every_risk_action_name_is_a_real_registered_tool():
    for tier, names in RISK_ACTIONS.items():
        unknown = set(names) - REAL_TOOL_NAMES
        assert not unknown, f"RISK_ACTIONS['{tier}'] references non-existent tool(s): {unknown}"


def test_no_tool_name_appears_in_more_than_one_tier():
    seen: dict[str, str] = {}
    for tier, names in RISK_ACTIONS.items():
        for name in names:
            assert name not in seen, f"'{name}' appears in both '{seen.get(name)}' and '{tier}'"
            seen[name] = tier


def test_system_prompt_defaults_to_axiom_for_backward_compatibility():
    """Wunomo Projects Phase 0 (commit 4): every SYSTEM_PROMPTS variant
    used to hardcode the literal string "AXIOM" - now a {agent_name}
    template. No real call site passes agent_name yet (that's commit 5),
    so the default must reproduce the exact old behavior."""
    prompt = build_system_prompt(PersonalityMode.ENGINEER, OperationMode.ASSISTED)
    assert "You are AXIOM, an AI DataOps Engineer." in prompt


def test_system_prompt_substitutes_a_real_agent_name():
    prompt = build_system_prompt(PersonalityMode.FOUNDER, OperationMode.ADVISORY, agent_name="Nova")
    assert "You are Nova briefing a founder." in prompt
    assert "AXIOM" not in prompt


def test_every_personality_variant_has_exactly_one_name_placeholder():
    """A future edit to SYSTEM_PROMPTS that reintroduces a hardcoded name
    literal (instead of {agent_name}) would silently make that one
    variant immune to renaming - catch it here, not live."""
    for mode, template in SYSTEM_PROMPTS.items():
        assert "{agent_name}" in template, f"{mode} has no {{agent_name}} placeholder"
        assert "AXIOM" not in template, f"{mode} still hardcodes a literal AXIOM"


def test_get_risk_level_defaults_low_for_an_unlisted_real_tool():
    listed = {n for names in RISK_ACTIONS.values() for n in names}
    unlisted_real_tools = REAL_TOOL_NAMES - listed
    # Every real tool is expected to be explicitly classified now (the
    # whole point of this fix) -- if a new tool is added later without
    # updating RISK_ACTIONS, it silently defaults to "low", which is a
    # real risk-tier miscalibration risk, not a crash. Assert there are
    # none left unclassified today, so that gap is caught immediately for
    # any tool added after this fix rather than discovered live later.
    assert not unlisted_real_tools, (
        f"Tool(s) registered but not classified in any RISK_ACTIONS tier "
        f"(silently defaulting to 'low'): {unlisted_real_tools}"
    )


def test_high_tier_is_intentionally_empty_today():
    """Documents the real, current state rather than letting a future
    reader assume this is an oversight: no delete/drop/revoke-capable
    AXIOM tool exists anywhere in agent/tools/*.py today."""
    assert RISK_ACTIONS["high"] == []
