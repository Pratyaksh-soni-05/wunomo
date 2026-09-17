"""Approving a gated tool must run it. Found 2026-09-17 by a tester.

Item #7 moved detect_schema_drift behind the approval gate. The first time
anyone approved it, the Approvals centre answered
"Action 'detect_schema_drift' is not registered in TOOL_REGISTRY". The
dispatch path used a hand-maintained map of 10 action names; measured
against RISK_ACTIONS it covered 6 of the 20 tools that require approval,
and 4 of its entries were not tool names at all. The gate opened onto a
dead end for two-thirds of what it gated, and had done so since before
Item #7 -- that item only exposed it.

Dispatch now resolves through agent.tools.ALL_TOOLS, the registry the chat
graph and the Tasks executor already use. These tests are the guard that
the two can never diverge again, plus the reproduction.
"""

import uuid

import pytest
from sqlalchemy import select

from agent.approval_executor import TOOL_MAP
from agent.personality import RISK_ACTIONS
from models.all_models import ApprovalStatus, DataSource, SourceType
from modules.governance.policy_engine import PolicyEngine
from services.tenant_context import tenant_session

GATED = RISK_ACTIONS["medium"] + RISK_ACTIONS["high"]


# ── Guard: every gated tool is executable through the approval path ─────────

@pytest.mark.parametrize("name", GATED)
def test_every_gated_tool_resolves_to_a_real_tool(name):
    assert name in TOOL_MAP, f"{name} requires approval but cannot be executed after it"
    assert "tenant_id" in TOOL_MAP[name].args, f"{name} must accept tenant_id for the server to force it"


def test_no_gated_tool_is_a_phantom_name():
    """The inverse of the old registry's 4 phantom entries."""
    real = set(TOOL_MAP)
    assert set(GATED) <= real, sorted(set(GATED) - real)


def test_the_old_registry_is_gone():
    import modules.governance.policy_engine as pe
    assert not hasattr(pe, "TOOL_REGISTRY"), "a second hand-kept list has come back"


# ── Reproduction: approve detect_schema_drift, and it runs ───────────────────

async def _tenant_with_csv(client, tmp_path):
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"appr-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Appr", "tenant_name": f"Appr Corp {uuid.uuid4().hex[:6]}",
    })).json()
    p = tmp_path / "t.csv"
    p.write_text("a,b,c\n1,2,3\n4,5,6\n")
    source_id = str(uuid.uuid4())
    async with tenant_session(reg["tenant_id"]) as db:
        db.add(DataSource(id=source_id, tenant_id=reg["tenant_id"], name="t",
                          source_type=SourceType.CSV, connection_config={"file_path": str(p)},
                          # stale on purpose: the file has three columns
                          schema_snapshot={"main": {"row_count": 2, "columns": [
                              {"column_name": "a", "data_type": "int64", "is_nullable": "YES"}]}}))
        await db.commit()
    return reg, source_id


@pytest.mark.asyncio
async def test_approving_detect_schema_drift_actually_runs_it(client, tmp_path):
    """The exact click that failed: approval row carries the model's args
    (source_id + a tenant_id), reviewer approves, the tool must run and
    the stale snapshot must be rewritten."""
    reg, source_id = await _tenant_with_csv(client, tmp_path)
    engine = PolicyEngine(reg["tenant_id"])
    created = await engine.create_request(
        user_id=reg["user_id"], session_id=str(uuid.uuid4()), action_name="detect_schema_drift",
        action_args={"source_id": source_id, "tenant_id": "whatever-the-model-said"},
        risk_level="medium", reason="test")
    out = await engine.approve(created["approval_id"], reviewer="tester")
    assert out["status"] == ApprovalStatus.EXECUTED.value, out
    res = out["execution_result"]
    assert "error" not in res, res
    assert res.get("has_drift") is True, res
    assert set(res["column_changes"]["main"]["added_columns"]) == {"b", "c"}
    async with tenant_session(reg["tenant_id"]) as db:
        snap = (await db.execute(select(DataSource.schema_snapshot).where(
            DataSource.id == source_id))).scalar_one()
    assert [c["column_name"] for c in snap["main"]["columns"]] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_identity_args_are_forced_from_the_approval_row(client, tmp_path, monkeypatch):
    """A stored tenant_id pointing at another tenant must not be honoured;
    the row's tenant wins, exactly as agent_node forces it on live calls."""
    reg, source_id = await _tenant_with_csv(client, tmp_path)
    seen = {}
    import agent.approval_executor as ax
    real = ax.TOOL_MAP["profile_schema"]

    class Spy:
        name = real.name
        args = real.args
        async def ainvoke(self, a):
            seen.update(a)
            return {"ok": True}
    monkeypatch.setitem(ax.TOOL_MAP, "profile_schema", Spy())

    engine = PolicyEngine(reg["tenant_id"])
    created = await engine.create_request(
        user_id=reg["user_id"], session_id="sess-1", action_name="profile_schema",
        action_args={"source_id": source_id, "tenant_id": "attacker-tenant", "bogus": 1},
        risk_level="medium", reason="test")
    out = await engine.approve(created["approval_id"], reviewer="tester")
    assert out["status"] == ApprovalStatus.EXECUTED.value, out
    assert seen["tenant_id"] == reg["tenant_id"]
    assert "bogus" not in seen                     # undeclared args are dropped, not 500ed


@pytest.mark.asyncio
async def test_unknown_action_still_fails_cleanly(client, tmp_path):
    reg, _ = await _tenant_with_csv(client, tmp_path)
    engine = PolicyEngine(reg["tenant_id"])
    created = await engine.create_request(
        user_id=reg["user_id"], session_id="s", action_name="cicd_pipeline_deployment",
        action_args={}, risk_level="high", reason="orphan mirror")
    out = await engine.approve(created["approval_id"], reviewer="tester")
    assert out["status"] == ApprovalStatus.FAILED.value
    assert "not a registered tool" in out["execution_result"]["error"]
