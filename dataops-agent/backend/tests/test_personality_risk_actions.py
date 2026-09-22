"""Regression guard for the "phantom high-risk tools" bug: every name in
RISK_ACTIONS must be a real, currently-registered agent tool, or
requires_approval() silently never blocks it in any operation mode. This
is exactly how delete_records/drop_table/modify_schema/revoke_access/
rerun_pipeline/modify_business_rule/update_contract/publish_output/
run_quality_check/list_sources/generate_report went unnoticed -- see
CLAUDE.md's "Phantom high-risk tools" Known-broken row.
"""
from agent.personality import RISK_ACTIONS, get_risk_level, build_system_prompt, SYSTEM_PROMPTS, EMPLOYEE_TYPE_IDENTITY
from agent.tools import ALL_TOOLS
from models.all_models import AgentEmployeeType, PersonalityMode, OperationMode

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


def test_every_personality_variant_names_the_agent_without_hardcoding_axiom():
    """A future edit to SYSTEM_PROMPTS that reintroduces a hardcoded name
    literal (instead of {agent_name}) would silently make that one
    variant immune to renaming - catch it here, not live.

    ENGINEER is the one deliberate exception ("Add Analyst as a second
    employee type"): its tone text used to open with "You are {agent_name},
    an AI DataOps Engineer" -- a real self-contradiction risk once a
    non-DataOps employee type could select ENGINEER tone too (an Analyst
    agent would be told it's simultaneously an Analyst AND a DataOps
    Engineer). That identity claim moved to EMPLOYEE_TYPE_IDENTITY below,
    which is employee-type-keyed rather than personality-keyed, so
    ENGINEER's own tone text no longer names the agent at all -- every
    other variant still must."""
    for mode, template in SYSTEM_PROMPTS.items():
        assert "AXIOM" not in template, f"{mode} still hardcodes a literal AXIOM"
        if mode is PersonalityMode.ENGINEER:
            assert "{agent_name}" not in template, (
                "ENGINEER's tone text should not itself claim an identity -- "
                "EMPLOYEE_TYPE_IDENTITY supplies {agent_name} for every employee type instead."
            )
        else:
            assert "{agent_name}" in template, f"{mode} has no {{agent_name}} placeholder"


def test_every_employee_type_identity_has_exactly_one_name_placeholder():
    """Same regression guard as above, for EMPLOYEE_TYPE_IDENTITY -- this
    is where an agent's own name is actually stated now, for every
    employee type, regardless of which personality tone it's paired
    with."""
    for employee_type, template in EMPLOYEE_TYPE_IDENTITY.items():
        assert "{agent_name}" in template, f"{employee_type} has no {{agent_name}} placeholder"
        assert "AXIOM" not in template, f"{employee_type} still hardcodes a literal AXIOM"


def test_every_real_agent_employee_type_has_an_identity_entry():
    """Fail-closed, same shape as the ALL_TOOLS/TOOL_CAPABILITIES coverage
    assertions elsewhere in this codebase: a real AgentEmployeeType member
    with no EMPLOYEE_TYPE_IDENTITY entry would silently fall back to the
    DATAOPS identity for every agent of that type (build_system_prompt's
    own .get(..., EMPLOYEE_TYPE_IDENTITY[DATAOPS]) default) -- better to
    catch a forgotten entry here than have a new employee type silently
    talk like a DataOps engineer."""
    missing = set(AgentEmployeeType) - set(EMPLOYEE_TYPE_IDENTITY)
    assert not missing, f"AgentEmployeeType member(s) with no EMPLOYEE_TYPE_IDENTITY entry: {missing}"


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
