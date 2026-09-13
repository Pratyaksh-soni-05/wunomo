"""Item #10 -- PHI/PII column classification and enforcement.

WHAT EXISTED (measured before building)

The schema snapshot stored, per column, only `column_name / data_type /
is_nullable` (plus null_count/unique_count for files). No sensitivity, no
sample values. Column names reached the LLM through
TransformGenerator._resolve_schema; row VALUES reached the LLM through the
preview_source_data tool and through execute_sql_transform /
run_python_transform tool results, and reached people through
GET /sources/{id}/preview and the /transformations/run|preview endpoints.
log_transform_run persisted a row preview into transform_runs -- a storage
sink that would have kept the values even after the response was masked.

WHAT THIS FILE PROVES

  * detection: the name battery (true positives AND the false positives the
    ranking called out -- `id` must not flag from `ssn`), and the value
    battery on columns whose names carry no signal at all;
  * the profiler writes the classification into the snapshot and never
    persists the sample values it judged from;
  * the manual override endpoint: gated to `sources.classify`, audited,
    and surviving a re-profile;
  * the request spy: the bytes the Groq SDK hands to httpx for the real
    outbound HTTPS request contain the safe column names and none of the
    flagged names or values;
  * preview and transform enforcement, human (mask) and LLM (strip), and the
    transform_runs storage sink;
  * a schema with nothing sensitive passes through every path untouched.
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from config import settings
from models.all_models import AuditLog, DataSource, SourceType, TransformRun, User
from modules.ingestion.connector_manager import ConnectorManager
from modules.ingestion.schema_profiler import SchemaProfiler
from modules.transformation.transform_generator import TransformGenerator
from services import pii_classifier
from services.pii_classifier import classify_column
from services.tenant_context import tenant_session


# ── Fixtures ─────────────────────────────────────────────────────────────────

SENSITIVE_ROWS = [
    # id, customer_email, ssn, phone, product_name, amount, region, notes
    (1, "alice.wu@example.com", "512-34-6789", "+1 415 555 0101", "Widget", 10.5, "west", "first order"),
    (2, "bob.ng@example.com", "521-45-7890", "+1 415 555 0102", "Gadget", 22.0, "east", "repeat"),
    (3, "cara.li@example.com", "532-56-8901", "+1 415 555 0103", "Widget", 7.25, "west", "gift"),
    (4, "dan.ok@example.com", "543-67-9012", "+1 415 555 0104", "Gizmo", 99.0, "north", ""),
]
SENSITIVE_HEADER = "id,customer_email,ssn,phone,product_name,amount,region,notes"
# Every value that must never reach an LLM provider.
LEAK_VALUES = [r[1] for r in SENSITIVE_ROWS] + [r[2] for r in SENSITIVE_ROWS] + [r[3] for r in SENSITIVE_ROWS]
FLAGGED = {"customer_email", "ssn", "phone"}
SAFE = {"id", "product_name", "amount", "region", "notes"}

CLEAN_HEADER = "id,product_name,amount,region,created_at"
CLEAN_ROWS = [(1, "Widget", 10.5, "west", "2026-01-01"), (2, "Gadget", 22.0, "east", "2026-01-02"),
              (3, "Gizmo", 7.25, "west", "2026-01-03")]


async def _register(client):
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"pii-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "PII Test", "tenant_name": f"PII Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return reg["access_token"], reg["tenant_id"], reg["user_id"]


def _write_csv(tmp_path, header, rows):
    p = tmp_path / f"{uuid.uuid4().hex[:8]}.csv"
    lines = [header] + [",".join(str(v) for v in r) for r in rows]
    p.write_text("\n".join(lines) + "\n")
    return str(p)


async def _csv_source(tenant_id, path):
    source_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(DataSource(id=source_id, tenant_id=tenant_id, name=f"src-{source_id[:6]}",
                          source_type=SourceType.CSV, connection_config={"file_path": path},
                          schema_snapshot={}))
        await db.commit()
    return source_id


async def _snapshot(tenant_id, source_id):
    async with tenant_session(tenant_id) as db:
        return (await db.execute(select(DataSource.schema_snapshot).where(
            DataSource.id == source_id))).scalar_one()


@pytest.fixture
async def sensitive_source(client, tmp_path):
    token, tenant_id, user_id = await _register(client)
    source_id = await _csv_source(tenant_id, _write_csv(tmp_path, SENSITIVE_HEADER, SENSITIVE_ROWS))
    out = await SchemaProfiler(tenant_id, source_id).profile()
    assert "error" not in out, out
    return {"token": token, "tenant_id": tenant_id, "user_id": user_id, "source_id": source_id}


@pytest.fixture
async def clean_source(client, tmp_path):
    token, tenant_id, user_id = await _register(client)
    source_id = await _csv_source(tenant_id, _write_csv(tmp_path, CLEAN_HEADER, CLEAN_ROWS))
    out = await SchemaProfiler(tenant_id, source_id).profile()
    assert "error" not in out, out
    return {"token": token, "tenant_id": tenant_id, "user_id": user_id, "source_id": source_id}


class GroqSpy:
    """Captures the exact httpx.Request the Groq SDK sends and answers it.

    Patched at httpx.AsyncClient.send -- the last method before bytes leave
    the process -- so what is captured is the serialised request, not some
    intermediate message object that a later layer could still enrich.
    """
    def __init__(self, real_send):
        self.requests: list[httpx.Request] = []
        self._real_send = real_send

    async def send(self, client, request, *args, **kwargs):
        # The test client is also an httpx.AsyncClient (ASGI transport);
        # only the provider's traffic is intercepted.
        if request.url.host != "api.groq.com":
            return await self._real_send(client, request, *args, **kwargs)
        self.requests.append(request)
        body = {"id": "chatcmpl-spy", "object": "chat.completion", "created": 0,
                "model": settings.PRIMARY_LLM_MODEL,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": "```sql\nSELECT region, SUM(amount) FROM main GROUP BY region\n```"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        return httpx.Response(200, json=body, request=request)

    @property
    def wire_text(self) -> str:
        return "\n".join(r.content.decode("utf-8", "replace") for r in self.requests)


@pytest.fixture
def groq_spy(monkeypatch):
    """Route the primary LLM to Groq (declared provider, per Hard Rule 2) and
    intercept its outbound HTTP. Groq rather than Gemini because the Groq SDK
    is plain httpx; Gemini's client goes through google-api-core transports
    and can't be pinned at one method. Both providers receive the same
    message list from invoke_llm, so a leak into one is a leak into both."""
    spy = GroqSpy(httpx.AsyncClient.send)
    monkeypatch.setattr(settings, "PRIMARY_LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "PRIMARY_LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_not_a_real_key")
    # a plain function so the descriptor passes the client as first arg
    monkeypatch.setattr(httpx.AsyncClient, "send",
                        lambda client, request, *a, **k: spy.send(client, request, *a, **k))
    return spy


# ── Task 7: detection battery ────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    # PII by name
    ("ssn", "pii"), ("social_security_number", "pii"), ("email", "pii"),
    ("customer_email", "pii"), ("phone", "pii"), ("phone_number", "pii"),
    ("fax_number", "pii"), ("date_of_birth", "pii"), ("dateOfBirth", "pii"),
    ("dob", "pii"), ("first_name", "pii"), ("last_name", "pii"), ("full_name", "pii"),
    ("customer_name", "pii"), ("name", "pii"), ("street_address", "pii"),
    ("zip_code", "pii"), ("postal_code", "pii"), ("credit_card", "pii"),
    ("card_number", "pii"), ("iban", "pii"), ("ip_address", "pii"), ("ip", "pii"),
    ("username", "pii"), ("password", "pii"), ("password_hash", "pii"),
    ("api_key", "pii"), ("salary", "pii"), ("gender", "pii"), ("passport_number", "pii"),
    # PHI by name
    ("diagnosis", "phi"), ("diagnosis_code", "phi"), ("icd10_code", "phi"),
    ("medical_record_number", "phi"), ("mrn", "phi"), ("patient_name", "phi"),
    ("prescription", "phi"), ("blood_type", "phi"), ("lab_result", "phi"),
    ("insurance_provider", "phi"), ("member_id", "phi"), ("procedure_code", "phi"),
    ("medical_condition", "phi"),
    # NOT sensitive -- the false-positive checks
    ("id", "none"), ("session_id", "none"), ("user_id", "none"), ("address_id", "none"),
    ("email_verified", "none"), ("phone_count", "none"), ("login_count", "none"),
    ("description", "none"), ("notes", "none"), ("amount", "none"), ("region", "none"),
    ("created_at", "none"), ("order_total", "none"), ("item_code", "none"),
    ("status", "none"), ("average", "none"),          # 'age' must not match inside 'average'
    ("product_name", "none"), ("table_name", "none"), ("pipeline_name", "none"),
    ("company_name", "none"),                         # thing-names, not person-names
    ("llm_provider", "none"), ("payment_provider", "none"),
    ("filter_condition", "none"), ("stored_procedure", "none"), ("lab", "none"),
    ("warehouse_location", "none"),
])
def test_name_detection(name, expected):
    level, _ = classify_column(name, "text", [])
    assert level == expected, (name, level)


def test_boolean_typed_columns_never_flag():
    """`email` as a boolean is "has an email", not an email."""
    assert classify_column("email", "boolean", [])[0] == "none"
    assert classify_column("ssn", "bool", [])[0] == "none"


def test_substring_does_not_flag():
    """The ranking's exact example: 'id' vs 'ssn'. Tokens, not substrings."""
    assert classify_column("id", "integer", [])[0] == "none"
    assert classify_column("ssn", "text", [])[0] == "pii"
    # 'passport' inside 'passports_issued_total' -- suffix says it's a count
    assert classify_column("passports_issued_total", "integer", [])[0] == "none"


@pytest.mark.parametrize("values,expected,label", [
    (["123-45-6789", "987-65-4321", "555-12-3456"], "pii", "ssn"),
    (["a@x.io", "b@y.org", "c@z.co", "d@w.net"], "pii", "email"),
    (["4111111111111111", "5500000000000004", "340000000000009"], "pii", "card"),
    (["10.0.0.1", "192.168.1.20", "172.16.0.3"], "pii", "ipv4"),
    (["+1 415 555 0100", "(415) 555-0101", "415-555-0102"], "pii", "phone"),
    # false positives on values
    (["4111111111111112", "5500000000000005", "340000000000000"], "none", "card fails Luhn"),
    (["12345", "67890", "11111"], "none", "5-digit integers are not phones"),
    (["2026-01-01", "2026-02-02", "2026-03-03"], "none", "dates"),
    (["999.999.999.999", "1.2.3", "300.1.1.1"], "none", "not ipv4"),
    (["123-45-6789", "hello", "world", "again", "more"], "none", "1/5 below threshold"),
    (["123-45-6789"], "none", "too few samples to judge"),
    (["000-12-3456", "666-12-3456", "912-12-3456"], "none", "invalid SSN area numbers"),
])
def test_value_detection_on_neutral_names(values, expected, label):
    level, reason = classify_column("col_x", "text", values)
    assert level == expected, (label, level, reason)


# ── Task 2/3: the profiler writes classification, never samples ──────────────

@pytest.mark.asyncio
async def test_profiler_classifies_and_persists_no_values(sensitive_source):
    snap = await _snapshot(sensitive_source["tenant_id"], sensitive_source["source_id"])
    cols = {c["column_name"]: c for c in snap["main"]["columns"]}
    assert {n for n, c in cols.items() if c["sensitivity"] in ("pii", "phi")} == FLAGGED
    for n in SAFE:
        assert cols[n]["sensitivity"] == "none"
    assert all(c["sensitivity_source"] == "auto" for c in cols.values())
    assert cols["ssn"]["sensitivity_reason"]
    # samples judged from must not be persisted
    dumped = json.dumps(snap)
    for v in LEAK_VALUES:
        assert v not in dumped


# ── Task 4: manual override ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_override_is_audited_and_survives_reprofile(client, sensitive_source):
    s = sensitive_source
    h = {"Authorization": f"Bearer {s['token']}"}
    # upgrade a safe column
    r = await client.put(f"/api/v1/sources/{s['source_id']}/classification", headers=h,
                         json={"table": "main", "column": "notes", "sensitivity": "phi",
                               "reason": "free text with clinical detail"})
    assert r.status_code == 200, r.text
    assert r.json()["previous"] == "none"
    # downgrade a flagged one
    r = await client.put(f"/api/v1/sources/{s['source_id']}/classification", headers=h,
                         json={"table": "main", "column": "phone", "sensitivity": "none"})
    assert r.status_code == 200, r.text

    snap = await _snapshot(s["tenant_id"], s["source_id"])
    cols = {c["column_name"]: c for c in snap["main"]["columns"]}
    assert cols["notes"]["sensitivity"] == "phi" and cols["notes"]["sensitivity_source"] == "manual"
    assert cols["phone"]["sensitivity"] == "none" and cols["phone"]["sensitivity_source"] == "manual"

    # re-profile: the detector would say phone=pii, notes=none; manual wins
    await SchemaProfiler(s["tenant_id"], s["source_id"]).profile()
    snap = await _snapshot(s["tenant_id"], s["source_id"])
    cols = {c["column_name"]: c for c in snap["main"]["columns"]}
    assert cols["notes"]["sensitivity"] == "phi"
    assert cols["phone"]["sensitivity"] == "none"
    assert cols["ssn"]["sensitivity"] == "pii" and cols["ssn"]["sensitivity_source"] == "auto"

    async with tenant_session(s["tenant_id"]) as db:
        rows = (await db.execute(select(AuditLog).where(
            AuditLog.tenant_id == s["tenant_id"],
            AuditLog.action == "source.column_classified"))).scalars().all()
    assert len(rows) == 2
    assert {r.payload["column"] for r in rows} == {"notes", "phone"}


@pytest.mark.asyncio
async def test_manual_override_rejects_bad_level_and_unknown_column(client, sensitive_source):
    s = sensitive_source
    h = {"Authorization": f"Bearer {s['token']}"}
    r = await client.put(f"/api/v1/sources/{s['source_id']}/classification", headers=h,
                         json={"table": "main", "column": "ssn", "sensitivity": "secret"})
    assert r.status_code == 422
    r = await client.put(f"/api/v1/sources/{s['source_id']}/classification", headers=h,
                         json={"table": "main", "column": "nope", "sensitivity": "pii"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_manual_override_needs_sources_classify(client, sensitive_source):
    """Analyst holds sources.profile (can re-profile) but not sources.classify
    (cannot lift masking). Viewer holds neither."""
    from services.rbac import PERMISSIONS
    from services.auth_service import issue_token_for_user
    s = sensitive_source
    assert "data_analyst" not in PERMISSIONS["sources.classify"]
    assert "data_engineer" in PERMISSIONS["sources.classify"]
    for role in ("data_analyst", "viewer"):
        async with tenant_session(s["tenant_id"]) as db:
            u = (await db.execute(select(User).where(User.id == s["user_id"]))).scalar_one()
            u.role = role
            await db.commit()
            tok = issue_token_for_user(u, "password")
        r = await client.put(f"/api/v1/sources/{s['source_id']}/classification",
                             headers={"Authorization": f"Bearer {tok}"},
                             json={"table": "main", "column": "ssn", "sensitivity": "none"})
        assert r.status_code == 403, (role, r.text)
    snap = await _snapshot(s["tenant_id"], s["source_id"])
    assert {c["column_name"]: c["sensitivity"] for c in snap["main"]["columns"]}["ssn"] == "pii"


# ── Task 6: the request spy ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_spy_flagged_columns_never_reach_the_provider(sensitive_source, groq_spy):
    s = sensitive_source
    out = await TransformGenerator(s["tenant_id"]).generate_sql(
        "total amount by region", source_id=s["source_id"])
    assert "error" not in out, out
    assert groq_spy.requests, "no outbound request was made"
    req = groq_spy.requests[0]
    assert req.url.host == "api.groq.com" and req.url.scheme == "https"
    wire = groq_spy.wire_text
    # the schema DID reach the model...
    for col in SAFE:
        assert col in wire, f"safe column {col} missing from prompt"
    assert "withheld" in wire   # ...and the model is told something was
    # ...but nothing sensitive did, by name or by value
    for col in FLAGGED:
        assert col not in wire, f"flagged column name {col} leaked"
    for v in LEAK_VALUES:
        assert v not in wire, f"value {v} leaked"
    assert out["schema_used"] is True


@pytest.mark.asyncio
async def test_request_spy_manual_override_is_honoured_in_the_prompt(client, sensitive_source, groq_spy):
    """Downgrade phone -> none, upgrade region -> pii; the very next prompt
    reflects both, proving enforcement reads the stored classification and
    not a cached auto-detection."""
    s = sensitive_source
    h = {"Authorization": f"Bearer {s['token']}"}
    for col, lvl in (("phone", "none"), ("region", "pii")):
        r = await client.put(f"/api/v1/sources/{s['source_id']}/classification", headers=h,
                             json={"table": "main", "column": col, "sensitivity": lvl})
        assert r.status_code == 200
    await TransformGenerator(s["tenant_id"]).generate_sql("count rows", source_id=s["source_id"])
    wire = groq_spy.wire_text
    assert "phone" in wire
    assert "region" not in wire
    assert "ssn" not in wire


@pytest.mark.asyncio
async def test_request_spy_preview_tool_result_is_stripped(sensitive_source):
    """The agent's preview_source_data tool -- its return value is what
    becomes the ToolMessage sent back to the provider on the next turn."""
    from agent.tools.ingestion_tools import preview_source_data
    s = sensitive_source
    res = await preview_source_data.ainvoke({"tenant_id": s["tenant_id"],
                                             "source_id": s["source_id"], "table": "main"})
    dumped = json.dumps(res, default=str)
    for col in FLAGGED:
        assert col not in dumped
    for v in LEAK_VALUES:
        assert v not in dumped
    assert "masked_columns" not in res          # names must not leak via the list either
    assert set(res["columns"]) == SAFE
    assert set(res["rows"][0]) == SAFE


@pytest.mark.asyncio
async def test_request_spy_python_transform_tool_result_is_stripped(sensitive_source):
    from agent.tools.transformation_tools import run_python_transform
    s = sensitive_source
    res = await run_python_transform.ainvoke({
        "tenant_id": s["tenant_id"], "user_id": s["user_id"], "session_id": str(uuid.uuid4()),
        "source_id": s["source_id"], "script": "result_df = df",
    })
    assert "error" not in res, res
    dumped = json.dumps(res, default=str)
    for col in FLAGGED:
        assert col not in dumped
    for v in LEAK_VALUES:
        assert v not in dumped
    assert set(res["columns"]) == SAFE
    # the storage sink: transform_runs.result_preview
    async with tenant_session(s["tenant_id"]) as db:
        run = (await db.execute(select(TransformRun).where(
            TransformRun.tenant_id == s["tenant_id"]).order_by(TransformRun.created_at.desc())
        )).scalars().first()
    stored = json.dumps(run.result_preview, default=str)
    for v in LEAK_VALUES:
        assert v not in stored


# ── Task 5/6: preview + transform enforcement for people ─────────────────────

@pytest.mark.asyncio
async def test_human_preview_masks_values_but_keeps_column(client, sensitive_source):
    s = sensitive_source
    r = await client.get(f"/api/v1/sources/{s['source_id']}/preview",
                         headers={"Authorization": f"Bearer {s['token']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["masked_columns"]) == FLAGGED
    assert set(body["columns"]) == FLAGGED | SAFE           # column still visible
    for row in body["rows"]:
        for col in FLAGGED:
            assert row[col] == pii_classifier.MASK
    assert body["rows"][0]["product_name"] == "Widget"      # safe values intact
    dumped = r.text
    for v in LEAK_VALUES:
        assert v not in dumped


@pytest.mark.asyncio
async def test_human_transform_endpoints_mask_and_storage_sink_is_clean(client, sensitive_source):
    s = sensitive_source
    h = {"Authorization": f"Bearer {s['token']}"}
    for path in ("/api/v1/transformations/run/pandas", "/api/v1/transformations/preview/pandas"):
        r = await client.post(path, headers=h,
                              json={"source_id": s["source_id"], "code": "result_df = df"})
        assert r.status_code == 200, (path, r.text)
        body = r.json()
        # Item #12 superseded masking for the pandas path: the flagged
        # columns are dropped from the frame before the sandbox ever sees
        # it, so they are absent here rather than masked. The invariant
        # this test guards -- no value in the response or the storage
        # sink -- is unchanged; see tests/test_pandas_column_access.py.
        assert "masked_columns" not in body
        assert set(body["columns"]) == SAFE
        for v in LEAK_VALUES:
            assert v not in r.text
    async with tenant_session(s["tenant_id"]) as db:
        runs = (await db.execute(select(TransformRun).where(
            TransformRun.tenant_id == s["tenant_id"]))).scalars().all()
    assert runs                                              # /run logged, /preview did not
    for run in runs:
        for v in LEAK_VALUES:
            assert v not in json.dumps(run.result_preview, default=str)


@pytest.mark.asyncio
async def test_unknown_table_falls_back_to_union(sensitive_source):
    """A caller naming a table the profiler never saw gets the union of all
    flagged columns, not nothing."""
    s = sensitive_source
    res = await ConnectorManager(s["tenant_id"]).preview(s["source_id"], table="whatever")
    assert set(res["masked_columns"]) == FLAGGED


# ── Task 8: nothing sensitive -> nothing changes ─────────────────────────────

@pytest.mark.asyncio
async def test_clean_schema_passes_through_untouched(client, clean_source, groq_spy):
    s = clean_source
    h = {"Authorization": f"Bearer {s['token']}"}
    snap = await _snapshot(s["tenant_id"], s["source_id"])
    assert all(c["sensitivity"] == "none" for c in snap["main"]["columns"])
    assert pii_classifier.sensitive_columns(snap) == {}

    r = await client.get(f"/api/v1/sources/{s['source_id']}/preview", headers=h)
    body = r.json()
    assert "masked_columns" not in body
    assert body["rows"][0]["product_name"] == "Widget"

    r = await client.post("/api/v1/transformations/run/pandas", headers=h,
                          json={"source_id": s["source_id"], "code": "result_df = df"})
    assert r.status_code == 200 and "masked_columns" not in r.json()
    assert r.json()["rows"][0]["region"] == "west"

    out = await TransformGenerator(s["tenant_id"]).generate_sql("total by region", source_id=s["source_id"])
    assert "error" not in out
    wire = groq_spy.wire_text
    for col in ("id", "product_name", "amount", "region", "created_at"):
        assert col in wire
    assert "withheld" not in wire

    from agent.tools.ingestion_tools import preview_source_data
    res = await preview_source_data.ainvoke({"tenant_id": s["tenant_id"],
                                             "source_id": s["source_id"], "table": "main"})
    assert set(res["columns"]) == {"id", "product_name", "amount", "region", "created_at"}


@pytest.mark.asyncio
async def test_unprofiled_source_is_classified_on_the_spot(client, tmp_path):
    """A registered-but-never-profiled source has schema_snapshot == {}.
    That is not a licence to release rows: the result's own columns are
    classified from name + the values in hand, nothing persisted."""
    from agent.tools.transformation_tools import run_python_transform
    token, tenant_id, user_id = await _register(client)
    source_id = await _csv_source(tenant_id, _write_csv(tmp_path, SENSITIVE_HEADER, SENSITIVE_ROWS))
    assert await _snapshot(tenant_id, source_id) == {}
    res = await run_python_transform.ainvoke({
        "tenant_id": tenant_id, "user_id": user_id, "session_id": str(uuid.uuid4()),
        "source_id": source_id, "script": "result_df = df",
    })
    assert "error" not in res, res
    dumped = json.dumps(res, default=str)
    for v in LEAK_VALUES:
        assert v not in dumped
    assert set(res["columns"]) == SAFE
    assert await _snapshot(tenant_id, source_id) == {}   # still unprofiled
    # the human path: since Item #12 the pandas frame never carried the
    # columns, so they are absent rather than masked (see test_pandas_column_access.py)
    r = await client.post("/api/v1/transformations/preview/pandas",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"source_id": source_id, "code": "result_df = df"})
    assert r.status_code == 200 and set(r.json()["columns"]) == SAFE
    for v in LEAK_VALUES:
        assert v not in r.text
