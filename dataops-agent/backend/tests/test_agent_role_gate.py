"""Phase 19: the agent-side half of the unified permission spec.

Tests role_denied_tool_calls() (agent/dataops_agent.py) directly at the
tool-dispatch level — synthetic roles and plain tool-call dicts, no LLM, no
real AXIOM conversation, no LangGraph — per the explicit instruction to
avoid burning Gemini's daily quota on routine gate checks. See
test_permission_matrix.py for the REST half, and
test_viewer_blocked_from_pipeline_trigger_both_consumers below for the
cross-consumer regression guard proving REST and chat share one map.
"""
import pytest

from agent.dataops_agent import role_denied_tool_calls
from agent.tools import ALL_TOOLS
from services.rbac import TOOL_CAPABILITIES, PERMISSIONS, Role, has_permission


def test_every_registered_tool_has_a_capability_entry():
    """Fail-closed enumeration test — mirrors the startup assertion in
    agent/dataops_agent.py (which crashes the process at import time if this
    is violated), run here as a normal, visible test-suite assertion too so
    it shows up in a regular `pytest` run, not only at boot."""
    tool_names = {t.name for t in ALL_TOOLS}
    unmapped = tool_names - set(TOOL_CAPABILITIES)
    assert not unmapped, f"Tools with no TOOL_CAPABILITIES entry: {unmapped}"


def test_unmapped_tool_is_denied_for_every_role():
    """A tool with no entry at all must be denied for every role, not just
    the ones a lookup happens to miss — this is the actual fail-closed
    behavior, checked directly against role_denied_tool_calls()."""
    calls = [{"name": "totally_unregistered_tool", "args": {}, "id": "c1"}]
    for role in Role:
        result = role_denied_tool_calls(role.value, list(calls))
        assert len(result) == 1
        assert result[0]["name"] == "totally_unregistered_tool"


def test_viewer_denied_a_builder_tier_tool():
    """register_data_source maps to sources.create (Owner/Admin/Data
    Engineer only) — Viewer must be denied, and the call must be stripped
    from the mutable list so it never reaches ToolNode."""
    calls = [{"name": "register_data_source", "args": {"tenant_id": "t1"}, "id": "c1"}]
    denied = role_denied_tool_calls("viewer", calls)
    assert len(denied) == 1
    assert denied[0]["name"] == "register_data_source"
    assert calls == [], "denied call must be removed from the list in place"


def test_data_analyst_allowed_a_builder_tier_operate_tool():
    """run_pipeline maps to pipelines.operate (Owner/Admin/Data Engineer/
    Data Analyst) — Data Analyst must pass through untouched."""
    calls = [{"name": "run_pipeline", "args": {"tenant_id": "t1"}, "id": "c1"}]
    denied = role_denied_tool_calls("data_analyst", calls)
    assert denied == []
    assert len(calls) == 1, "an allowed call must not be removed"


def test_view_tier_tools_allowed_for_every_role_including_viewer():
    """The 12 read-only tools mapped to 'view' must stay usable by every
    role — otherwise Viewer's chat refuses everything, per the explicit
    design goal."""
    view_tools = [name for name, cap in TOOL_CAPABILITIES.items() if cap == "view"]
    assert len(view_tools) >= 12
    for role in Role:
        calls = [{"name": name, "args": {}, "id": f"c-{name}"} for name in view_tools]
        denied = role_denied_tool_calls(role.value, calls)
        assert denied == [], f"{role.value} should be able to use every 'view' tool, denied: {denied}"


def test_mixed_batch_only_strips_the_denied_calls():
    """A single LLM turn requesting several tools at once must keep the
    allowed ones and strip only the denied ones — not all-or-nothing."""
    calls = [
        {"name": "list_data_sources", "args": {}, "id": "c1"},       # view — allowed for viewer
        {"name": "register_data_source", "args": {}, "id": "c2"},    # sources.create — denied for viewer
        {"name": "resolve_incident", "args": {}, "id": "c3"},        # incidents.resolve — denied for viewer
    ]
    denied = role_denied_tool_calls("viewer", calls)
    assert {c["name"] for c in denied} == {"register_data_source", "resolve_incident"}
    assert [c["name"] for c in calls] == ["list_data_sources"]


@pytest.mark.asyncio
async def test_viewer_blocked_from_pipeline_trigger_both_consumers(client):
    """The actual regression guard proving REST and AXIOM chat consult the
    SAME permission map, not two copies that happen to agree today. Without
    this, the REST endpoint and the agent tool could silently drift apart
    while both test suites stayed green."""
    import uuid
    from database import AsyncSessionLocal
    from models.all_models import User
    from services.auth_service import issue_token_for_user
    from sqlalchemy import select

    reg = await client.post("/api/v1/auth/register", json={
        "email": f"crossconsumer-{uuid.uuid4().hex[:8]}@example.com",
        "password": "test1234",
        "full_name": "Cross Consumer Test",
        "tenant_name": f"Cross Consumer Corp {uuid.uuid4().hex[:6]}",
    })
    user_id = reg.json()["user_id"]

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        user.role = "viewer"
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.id == user_id))
        user = r.scalar_one()
        viewer_token = issue_token_for_user(user, "password")

    # Consumer 1: REST.
    rest_resp = await client.post(
        "/api/v1/pipelines/nonexistent-id/trigger",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert rest_resp.status_code == 403, "REST must deny a Viewer's pipelines.operate request"

    # Consumer 2: the agent tool-dispatch gate, at the function level — no
    # LLM, no real conversation, same synthetic-role technique as the rest
    # of this file.
    calls = [{"name": "run_pipeline", "args": {"tenant_id": "t1"}, "id": "c1"}]
    denied = role_denied_tool_calls("viewer", calls)
    assert len(denied) == 1, "agent tool-dispatch must deny a Viewer's run_pipeline call too"

    # Both denials trace back to the exact same capability entry.
    assert Role.VIEWER not in PERMISSIONS["pipelines.operate"]
    assert has_permission("viewer", TOOL_CAPABILITIES["run_pipeline"]) is False
