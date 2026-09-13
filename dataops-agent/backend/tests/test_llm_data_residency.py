"""Item #11 -- GDPR data residency for LLM calls.

MEASURED FIRST: what Item #10 already enforced

Every outbound LLM call in the codebase goes through services/llm_service.py
(invoke_llm for transform generation, task planning and task-step
adaptation; _TimeoutFallbackChatModel for the chat graph). The data that
reaches those calls: the user's text, the system prompt, schema metadata
from _resolve_schema, and tool results. Item #10 strips pii/phi columns
(name and value) from _resolve_schema and from every tool that returns
row values (preview_source_data, execute_sql_transform,
run_python_transform). Quality, observability and reporting tools return
counts, names and timestamps, not row values (measured by reading each
backing module). So (a) of the ranking's fix list -- a pre-LLM filter --
is already satisfied by #10; what #10 had NOT proven is the full chat turn:
the graph's own request, carrying a ToolMessage, at the wire. That is
test_chat_turn below.

Genuinely new in #11: the residency setting and its gate, and the
customer-facing data-flow document.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from config import settings
from models.all_models import DataSource, SourceType
from modules.ingestion.schema_profiler import SchemaProfiler
from services import llm_service
from services.llm_service import DataResidencyError
from services.tenant_context import tenant_session

pytestmark = pytest.mark.asyncio

ROWS = [
    (1, "alice.wu@example.com", "512-34-6789", "Widget", 10.5, "west"),
    (2, "bob.ng@example.com", "521-45-7890", "Gadget", 22.0, "east"),
    (3, "cara.li@example.com", "532-56-8901", "Widget", 7.25, "west"),
]
HEADER = "id,customer_email,ssn,product_name,amount,region"
LEAK_VALUES = [r[1] for r in ROWS] + [r[2] for r in ROWS]
FLAGGED = {"customer_email", "ssn"}
SAFE = {"id", "product_name", "amount", "region"}


async def _tenant_with_source(client, tmp_path):
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"res-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Residency", "tenant_name": f"Res Corp {uuid.uuid4().hex[:6]}",
    })).json()
    p = tmp_path / "customers.csv"
    p.write_text("\n".join([HEADER] + [",".join(map(str, r)) for r in ROWS]) + "\n")
    source_id = str(uuid.uuid4())
    async with tenant_session(reg["tenant_id"]) as db:
        db.add(DataSource(id=source_id, tenant_id=reg["tenant_id"], name="customers",
                          source_type=SourceType.CSV, connection_config={"file_path": str(p)},
                          schema_snapshot={}))
        await db.commit()
    out = await SchemaProfiler(reg["tenant_id"], source_id).profile()
    assert "error" not in out, out
    return reg["tenant_id"], reg["user_id"], source_id


class ScriptedGroqSpy:
    """Same interception point as Item #10 (httpx.AsyncClient.send, the last
    hop before the network), but answers with a SCRIPT so a whole chat turn
    can be driven: reply 1 is a tool call, reply 2 is prose."""

    def __init__(self, real_send, replies):
        self.requests: list[httpx.Request] = []
        self._real_send = real_send
        self._replies = list(replies)

    async def send(self, client, request, *args, **kwargs):
        if request.url.host != "api.groq.com":
            return await self._real_send(client, request, *args, **kwargs)
        self.requests.append(request)
        message = self._replies.pop(0) if self._replies else {"role": "assistant", "content": "done"}
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        body = {"id": "chatcmpl-spy", "object": "chat.completion", "created": 0,
                "model": settings.PRIMARY_LLM_MODEL,
                "choices": [{"index": 0, "finish_reason": finish, "message": message}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        return httpx.Response(200, json=body, request=request)

    def body(self, i) -> str:
        return self.requests[i].content.decode("utf-8", "replace")


@pytest.fixture
def groq_route(monkeypatch):
    """Route the primary to Groq by declared provider (Hard Rule 2) and make
    sure the agent is rebuilt with it -- get_agent() caches built agents,
    and a cached Gemini client would send the request somewhere the spy
    cannot see."""
    from agent import dataops_agent
    monkeypatch.setattr(settings, "PRIMARY_LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "PRIMARY_LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "FALLBACK_LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_not_a_real_key")
    saved = dict(dataops_agent._cache)
    dataops_agent._cache.clear()
    yield
    dataops_agent._cache.clear()
    dataops_agent._cache.update(saved)


def _install(monkeypatch, replies):
    spy = ScriptedGroqSpy(httpx.AsyncClient.send, replies)
    monkeypatch.setattr(httpx.AsyncClient, "send",
                        lambda client, request, *a, **k: spy.send(client, request, *a, **k))
    return spy


# ── Task 5: a full chat turn, at the wire ────────────────────────────────────

async def test_chat_turn_never_sends_flagged_columns(client, tmp_path, groq_route, monkeypatch):
    """The ranking's own specified test. A user asks AXIOM to look at a
    source with pii columns; the model (scripted) calls preview_source_data;
    the graph runs the real tool and sends the ToolMessage back. Request 2
    is the one that would carry the rows."""
    from agent.dataops_agent import run_agent
    tenant_id, user_id, source_id = await _tenant_with_source(client, tmp_path)
    spy = _install(monkeypatch, [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_1", "type": "function", "function": {
             "name": "preview_source_data",
             "arguments": json.dumps({"tenant_id": "ignored", "source_id": source_id,
                                      "table": "main", "limit": 50})}}]},
        {"role": "assistant", "content": "Here is what I found."},
    ])

    res = await run_agent("show me a sample of the customers source",
                          tenant_id, user_id, str(uuid.uuid4()), "owner")
    assert "Here is what I found." in (res.get("response") or "")
    assert len(spy.requests) == 2, [r.url for r in spy.requests]
    assert all(r.url.host == "api.groq.com" and r.url.scheme == "https" for r in spy.requests)

    second = spy.body(1)
    assert "product_name" in second and "Widget" in second     # the tool result DID go
    for col in FLAGGED:
        assert col not in second, f"column name {col} in outbound payload"
    for v in LEAK_VALUES:
        assert v not in second, f"value {v} in outbound payload"
    # and nothing in the whole turn, either request, carried them
    for v in LEAK_VALUES:
        assert v not in spy.body(0)


async def test_chat_turn_with_clean_source_is_unchanged(client, tmp_path, groq_route, monkeypatch):
    """Nothing flagged -> every column and value reaches the model. Proves
    the previous test passes because of filtering, not because tool
    results never reach the wire."""
    from agent.dataops_agent import run_agent
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"res-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Residency", "tenant_name": f"Res Corp {uuid.uuid4().hex[:6]}",
    })).json()
    p = tmp_path / "orders.csv"
    p.write_text("id,product_name,amount,region\n1,Widget,10.5,west\n2,Gadget,22.0,east\n3,Gizmo,7.25,west\n")
    source_id = str(uuid.uuid4())
    async with tenant_session(reg["tenant_id"]) as db:
        db.add(DataSource(id=source_id, tenant_id=reg["tenant_id"], name="orders",
                          source_type=SourceType.CSV, connection_config={"file_path": str(p)},
                          schema_snapshot={}))
        await db.commit()
    await SchemaProfiler(reg["tenant_id"], source_id).profile()
    spy = _install(monkeypatch, [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_1", "type": "function", "function": {
             "name": "preview_source_data",
             "arguments": json.dumps({"tenant_id": "x", "source_id": source_id, "table": "main"})}}]},
        {"role": "assistant", "content": "ok"},
    ])
    await run_agent("preview orders", reg["tenant_id"], reg["user_id"], str(uuid.uuid4()), "owner")
    second = spy.body(1)
    for token in ("id", "product_name", "amount", "region", "Widget", "Gizmo", "22.0"):
        assert token in second


# ── Task 4: the residency setting ────────────────────────────────────────────

def test_default_mode_is_global_and_allows_calls():
    assert settings.LLM_DATA_RESIDENCY_MODE == "global"
    llm_service.assert_outbound_llm_allowed()
    st = llm_service.residency_status()
    assert st["outbound_llm_allowed"] is True and set(st["providers"]) == {"gemini", "groq"}


def test_unknown_mode_refuses_to_boot():
    from pydantic import ValidationError
    from config import Settings
    with pytest.raises(ValidationError, match="LLM_DATA_RESIDENCY_MODE"):
        Settings(LLM_DATA_RESIDENCY_MODE="us-east-1")
    # case/whitespace tolerant for the values that do exist
    assert Settings(LLM_DATA_RESIDENCY_MODE=" EU ").LLM_DATA_RESIDENCY_MODE == "eu"


@pytest.mark.parametrize("mode", ["eu", "self_hosted"])
async def test_unimplemented_modes_block_every_llm_path(mode, groq_route, monkeypatch):
    """Not a warning: a refusal, at each of the three places a call can
    originate, with zero bytes reaching any provider."""
    from langchain_core.messages import HumanMessage
    monkeypatch.setattr(settings, "LLM_DATA_RESIDENCY_MODE", mode)
    spy = _install(monkeypatch, [])
    st = llm_service.residency_status()
    assert st["outbound_llm_allowed"] is False and st["mode"] == mode

    # 1. no provider client can even be constructed
    with pytest.raises(DataResidencyError, match=mode):
        llm_service.get_primary_llm()
    with pytest.raises(DataResidencyError):
        llm_service.get_fallback_llm()

    # 2. invoke_llm (transform generation, task planning) -- and no retry
    #    backoff: this must fail in milliseconds, not after 3 attempts
    import time
    t0 = time.monotonic()
    with pytest.raises(DataResidencyError):
        await llm_service.invoke_llm([HumanMessage(content="hi")], tenant_id="t")
    assert time.monotonic() - t0 < 1.0

    # 3. the chat graph's model wrapper, even with clients built earlier
    monkeypatch.setattr(settings, "LLM_DATA_RESIDENCY_MODE", "global")
    wrapper = llm_service.get_llm_for_agent()
    monkeypatch.setattr(settings, "LLM_DATA_RESIDENCY_MODE", mode)
    with pytest.raises(DataResidencyError):
        await wrapper.ainvoke([HumanMessage(content="hi")])

    assert spy.requests == []


async def test_blocked_mode_surfaces_as_a_clean_transform_error(client, tmp_path, groq_route, monkeypatch):
    """A caller sees the refusal as an ordinary error result, not a 500."""
    from modules.transformation.transform_generator import TransformGenerator
    tenant_id, _, source_id = await _tenant_with_source(client, tmp_path)
    monkeypatch.setattr(settings, "LLM_DATA_RESIDENCY_MODE", "eu")
    spy = _install(monkeypatch, [])
    out = await TransformGenerator(tenant_id).generate_sql("count rows", source_id=source_id)
    assert "error" in out and "LLM_DATA_RESIDENCY_MODE" in out["error"]
    assert spy.requests == []


# ── Task 3: the document exists and names what the code does ─────────────────

def test_data_flow_document_matches_the_code():
    """Cheap drift guard: the customer-facing document must name the
    providers actually configured, the setting, its modes, and this test
    file. If one of those changes the document is stale, and a stale
    compliance document is worse than none."""
    from pathlib import Path
    from config import LLM_DATA_RESIDENCY_MODES
    here = Path(__file__).resolve()
    if len(here.parents) < 4:
        pytest.skip("repo root not visible from the backend container (./backend is the mount)")
    doc = here.parents[3] / "docs" / "compliance" / "LLM_DATA_FLOW.md"
    if not doc.parent.parent.exists():
        # The backend container mounts ./backend only; the repo-level docs/
        # tree is not visible there. Run this one from the host, or with
        # docs/ mounted, for the check to be live.
        pytest.skip(f"repo docs/ not visible from {doc.parent.parent}")
    assert doc.exists(), doc
    text = doc.read_text(encoding="utf-8")
    for needle in ("LLM_DATA_RESIDENCY_MODE", "DataResidencyError", "Gemini", "Groq",
                   "test_pii_classification.py", "test_llm_data_residency.py",
                   "ai.google.dev/gemini-api/terms", "groq.com/privacy-policy",
                   *(f"`{m}`" for m in LLM_DATA_RESIDENCY_MODES)):
        assert needle in text, f"LLM_DATA_FLOW.md no longer mentions {needle}"
