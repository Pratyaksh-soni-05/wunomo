"""detect_schema_drift: the first tests it has ever had (Item #7).

The security ranking flagged this tool as its highest blast-radius item for a
specific combination: zero tests, zero cited live run, reachable by every
role including Viewer, no approval gate in the default ASSISTED mode — while
writing to the database. Everything below is the measurement that turned
"the ranking says it writes" into "it writes, here is the before/after".

WHAT IT ACTUALLY DOES, MEASURED

Seeded a CSV source whose stored snapshot listed one column while the real
file had three. Before: snapshot ['a'], last_profiled_at 2026-01-01. Invoked
the real @tool wrapper. After: snapshot ['a','b','c'], row_count 2,
last_profiled_at advanced to now — committed. A second call with no drift
left both untouched, so the write is conditional on drift. That is the same
pair of columns profile_schema and sync_source write, and last_profiled_at
is the value the freshness sweep reads: a Viewer could reset a source's
staleness tracking through a tool whose name says "detect".

TWO GATES, AND WHICH ONE STOPS WHOM

  role gate      TOOL_CAPABILITIES  "view" -> "sources.profile"   stops Viewer
  approval gate  RISK_ACTIONS       "low"  -> "medium"            stops silent
                                                                  execution in
                                                                  ASSISTED for
                                                                  everyone else

They are independent and are tested independently. A Viewer's call is
stripped by the role gate before the approval gate ever sees it; an
analyst's call passes the role gate and is then held for approval. Both
values now match profile_schema, the sibling that performs the identical
write.
"""

import uuid
from datetime import datetime

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from agent import dataops_agent
from agent.dataops_agent import role_denied_tool_calls
from agent.personality import RISK_ACTIONS, get_risk_level, requires_approval
from agent.tools import ALL_TOOLS
from agent.tools.ingestion_tools import detect_schema_drift
from models.all_models import DataSource, OperationMode, SourceType
from services.rbac import TOOL_CAPABILITIES, has_permission
from services.tenant_context import tenant_session


# ── Declared tier ────────────────────────────────────────────────────────────

def test_is_medium_risk_not_low():
    """The tier change itself. Pinned so it cannot quietly drift back on the
    strength of the tool's name."""
    assert get_risk_level("detect_schema_drift") == "medium"
    assert "detect_schema_drift" in RISK_ACTIONS["medium"]
    assert "detect_schema_drift" not in RISK_ACTIONS["low"]


def test_requires_approval_in_assisted_mode():
    """ASSISTED is the default operation mode, so this is the case that
    matters. Before Item #7 this returned False."""
    assert requires_approval("detect_schema_drift", OperationMode.ASSISTED) is True
    assert requires_approval("detect_schema_drift", OperationMode.ADVISORY) is True
    assert requires_approval("detect_schema_drift", OperationMode.AUDIT) is True


def test_capability_matches_the_sibling_that_does_the_same_write():
    """It writes exactly what profile_schema writes, so it needs exactly the
    capability profile_schema needs. Was "view"."""
    assert TOOL_CAPABILITIES["detect_schema_drift"] == "sources.profile"
    assert TOOL_CAPABILITIES["detect_schema_drift"] == TOOL_CAPABILITIES["profile_schema"]


def test_viewer_can_no_longer_reach_it():
    assert not has_permission("viewer", TOOL_CAPABILITIES["detect_schema_drift"])
    for role in ("owner", "admin", "data_engineer", "data_analyst"):
        assert has_permission(role, TOOL_CAPABILITIES["detect_schema_drift"]), role


def test_role_gate_strips_a_viewer_call_before_it_can_execute():
    calls = [{"name": "detect_schema_drift", "args": {"source_id": "x"}, "id": "c1"}]
    denied = role_denied_tool_calls("viewer", calls)
    assert [d["name"] for d in denied] == ["detect_schema_drift"]
    assert calls == [], "the denied call must be removed from the batch, not just reported"


# ── The write, measured against a seeded tenant ──────────────────────────────

async def _register(client) -> str:
    r = await client.post("/api/v1/auth/register", json={
        "email": f"drift-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Drift Gating", "tenant_name": "Drift Gating Corp",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["tenant_id"]


async def _seed_stale_source(tenant_id: str, tmp_path) -> tuple[str, datetime]:
    """A CSV with three columns and a stored snapshot that only knows one, so
    the very first detect_drift call must find drift."""
    path = tmp_path / "drift.csv"
    path.write_text("a,b,c\n1,x,2.5\n2,y,3.5\n")
    stale = datetime(2026, 1, 1)
    source_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(DataSource(
            id=source_id, tenant_id=tenant_id, name="drift-src",
            source_type=SourceType.CSV, connection_config={"file_path": str(path)},
            schema_snapshot={"main": {"row_count": 0, "columns": [
                {"column_name": "a", "data_type": "int64", "is_nullable": "NO"}]}},
            last_profiled_at=stale,
        ))
        await db.commit()
    return source_id, stale


async def _read(tenant_id: str, source_id: str):
    async with tenant_session(tenant_id) as db:
        s = (await db.execute(select(DataSource).where(DataSource.id == source_id))).scalar_one()
        return ([c["column_name"] for c in s.schema_snapshot["main"]["columns"]],
                s.schema_snapshot["main"]["row_count"], s.last_profiled_at)


@pytest.mark.asyncio
async def test_it_really_writes_schema_snapshot_and_last_profiled_at(client, tmp_path):
    """The claim the whole ranking item rests on, measured through the real
    @tool wrapper against a real DataSource row, read back from a fresh
    session so nothing is served from identity-map cache."""
    tenant_id = await _register(client)
    source_id, stale = await _seed_stale_source(tenant_id, tmp_path)

    cols_before, rc_before, lpa_before = await _read(tenant_id, source_id)
    assert cols_before == ["a"] and lpa_before == stale

    result = await detect_schema_drift.ainvoke({"tenant_id": tenant_id, "source_id": source_id})
    assert result["has_drift"] is True
    assert sorted(result["column_changes"]["main"]["added_columns"]) == ["b", "c"]

    cols_after, rc_after, lpa_after = await _read(tenant_id, source_id)
    assert cols_after == ["a", "b", "c"], "schema_snapshot was not rewritten"
    assert rc_after == 2
    assert lpa_after > stale, "last_profiled_at was not advanced"


@pytest.mark.asyncio
async def test_the_write_is_conditional_on_drift(client, tmp_path):
    """Once the snapshot is current, a further call must not touch the row —
    otherwise every 'detect' would reset freshness tracking even with nothing
    to report."""
    tenant_id = await _register(client)
    source_id, _ = await _seed_stale_source(tenant_id, tmp_path)
    await detect_schema_drift.ainvoke({"tenant_id": tenant_id, "source_id": source_id})
    _, _, lpa_first = await _read(tenant_id, source_id)

    second = await detect_schema_drift.ainvoke({"tenant_id": tenant_id, "source_id": source_id})
    assert second["has_drift"] is False
    _, _, lpa_second = await _read(tenant_id, source_id)
    assert lpa_second == lpa_first


# ── The gates, end to end through the real agent graph ───────────────────────

class _ScriptedLLM:
    """bind_tools is a no-op; ainvoke replays scripted responses. Same shape
    as test_agent_graph's FakeToolCallLLM, kept local so this file does not
    import from another test module."""

    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def _llm_that_calls_detect_drift():
    return _ScriptedLLM([
        AIMessage(content="", tool_calls=[
            {"name": "detect_schema_drift",
             "args": {"tenant_id": "t", "source_id": "src-1"}, "id": "call_1"},
        ]),
        AIMessage(content="Done."),
    ])


@pytest.mark.asyncio
async def test_approval_gate_intercepts_it_for_an_analyst_in_assisted_mode(monkeypatch):
    """Real tool, real TOOL_CAPABILITIES, real requires_approval — only the
    LLM is scripted. data_analyst passes the role gate (sources.profile), so
    this is the approval gate doing the stopping, and the call must surface
    as a pending approval rather than execute."""
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent",
                        lambda temperature=0.0, primary_model=None: _llm_that_calls_detect_drift())
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS",
                        [t for t in ALL_TOOLS if t.name == "detect_schema_drift"])
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="has the schema drifted?",
        tenant_id="t1", user_id="u1", session_id="s1",
        caller_role="data_analyst", operation_mode="assisted",
    )

    assert [p["name"] for p in result["pending_approvals"]] == ["detect_schema_drift"]
    assert result["pending_approvals"][0]["risk_level"] == "medium"
    assert result.get("role_denied", []) == [], "analyst must not be role-denied"


@pytest.mark.asyncio
async def test_role_gate_stops_a_viewer_before_the_approval_gate(monkeypatch):
    """Same graph, caller_role=viewer. The call must be role-denied and must
    NOT appear as a pending approval — a Viewer cannot even request the write."""
    monkeypatch.setattr(dataops_agent, "get_llm_for_agent",
                        lambda temperature=0.0, primary_model=None: _llm_that_calls_detect_drift())
    monkeypatch.setattr(dataops_agent, "ALL_TOOLS",
                        [t for t in ALL_TOOLS if t.name == "detect_schema_drift"])
    dataops_agent._cache.clear()

    result = await dataops_agent.run_agent(
        user_message="has the schema drifted?",
        tenant_id="t1", user_id="u1", session_id="s1",
        caller_role="viewer", operation_mode="assisted",
    )

    assert [d["name"] for d in result.get("role_denied", [])] == ["detect_schema_drift"]
    assert result["pending_approvals"] == []
