"""Item #12 -- column-level access control in the Pandas executor.

THE DATA FLOW, MEASURED (before this change)

  run_on_source(source_id, code)
    -> _ast_check(code)                       python_guard, static      [parent]
    -> _load_dataframe(source_id)             reads the DataSource row  [parent]
         (the row INCLUDES schema_snapshot, so Item #10's classification
          is already in hand here -- nothing had to be threaded through)
         file: FileConnector.preview -> pd.DataFrame(rows)
         postgres: asyncpg SELECT * -> pd.DataFrame
    -> _execute(code, df)                                                [parent]
    -> python_sandbox.run_sandboxed(code, df.copy())                     [parent]
         pickle.dumps(df)  <-- the fork boundary: bytes handed to the child
    -> _child(code, df_bytes): pickle.loads, exec                        [child]

Before: the full frame, every column, was pickled and unpickled into the
child. Item #10 masked/stripped the RESULT afterwards, so a script could
not return an ssn -- but it had the column in memory the whole time and
could, e.g., fold it into another column. After: the columns are dropped
in _load_dataframe (and in run_on_dataframe), i.e. before _execute, before
pickle.dumps, before the fork. The tests below assert at that exact
boundary -- on the bytes pickle.dumps produces -- and inside the child.
"""

import pickle
import uuid

import pytest
import pandas as pd
from sqlalchemy import select

from models.all_models import DataSource, SourceType
from modules.ingestion.schema_profiler import SchemaProfiler
from modules.transformation import python_sandbox
from modules.transformation.python_runner import PythonRunner
from services.tenant_context import tenant_session

pytestmark = pytest.mark.asyncio

ROWS = [
    (1, "alice.wu@example.com", "512-34-6789", "Widget", 10.5, "west"),
    (2, "bob.ng@example.com", "521-45-7890", "Gadget", 22.0, "east"),
    (3, "cara.li@example.com", "532-56-8901", "Widget", 7.25, "west"),
    (4, "dan.ok@example.com", "543-67-9012", "Gizmo", 99.0, "north"),
]
HEADER = "id,customer_email,ssn,product_name,amount,region"
FLAGGED = {"customer_email", "ssn"}
SAFE = {"id", "product_name", "amount", "region"}
LEAK_VALUES = [r[1] for r in ROWS] + [r[2] for r in ROWS]


def _dump(obj) -> str:
    return repr(obj)


def _assert_clean(text: str):
    for v in LEAK_VALUES:
        assert v not in text, f"value {v} leaked"


async def _register(client):
    reg = (await client.post("/api/v1/auth/register", json={
        "email": f"col-{uuid.uuid4().hex[:8]}@example.com", "password": "test1234",
        "full_name": "Col", "tenant_name": f"Col Corp {uuid.uuid4().hex[:6]}",
    })).json()
    return reg["access_token"], reg["tenant_id"], reg["user_id"]


def _csv(tmp_path, header=HEADER, rows=ROWS):
    p = tmp_path / f"{uuid.uuid4().hex[:6]}.csv"
    p.write_text("\n".join([header] + [",".join(map(str, r)) for r in rows]) + "\n")
    return p


async def _source(tenant_id, path, profile=True):
    source_id = str(uuid.uuid4())
    async with tenant_session(tenant_id) as db:
        db.add(DataSource(id=source_id, tenant_id=tenant_id, name=f"s-{source_id[:6]}",
                          source_type=SourceType.CSV, connection_config={"file_path": str(path)},
                          schema_snapshot={}))
        await db.commit()
    if profile:
        out = await SchemaProfiler(tenant_id, source_id).profile()
        assert "error" not in out, out
    return source_id


@pytest.fixture
async def src(client, tmp_path):
    token, tenant_id, user_id = await _register(client)
    source_id = await _source(tenant_id, _csv(tmp_path))
    return {"token": token, "tenant_id": tenant_id, "user_id": user_id,
            "source_id": source_id, "path": tmp_path}


@pytest.fixture
def pickle_spy(monkeypatch):
    """Captures every byte string python_sandbox hands to the child. This is
    the fork boundary itself: run_sandboxed calls pickle.dumps(df) and
    passes the result as a Process arg."""
    captured = []
    real = pickle.dumps

    def spy(obj, *a, **k):
        data = real(obj, *a, **k)
        if isinstance(obj, pd.DataFrame):
            captured.append(data)
        return data
    monkeypatch.setattr(python_sandbox.pickle, "dumps", spy)
    return captured


# ── Task 3: the pickle boundary ──────────────────────────────────────────────

async def test_stripped_columns_never_cross_the_fork_boundary(src, pickle_spy):
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], "result_df = df")
    assert "error" not in res, res
    # first capture = the input frame the parent pickled for the child
    # (the child's own pickle of result_df happens in the child process and
    # is not visible to this monkeypatch -- a fork copies the patched
    # function too, but the list it appends to is the child's copy)
    assert pickle_spy, "nothing was pickled -- did the sandbox run?"
    inbound = pickle_spy[0]
    for col in FLAGGED:
        assert col.encode() not in inbound, f"column name {col} crossed the fork"
    for v in LEAK_VALUES:
        assert v.encode() not in inbound, f"value {v} crossed the fork"
    for col in SAFE:
        assert col.encode() in inbound
    assert b"Widget" in inbound
    # and what came back reflects the same frame
    assert set(res["columns"]) == SAFE
    _assert_clean(_dump(res))
    assert any("2 column(s) withheld" in w for w in res["warnings"])


# ── Task 5: explicit access gets a clear, non-leaky error ────────────────────

@pytest.mark.parametrize("code", [
    "result_df = df[['ssn']]",
    "result_df = pd.DataFrame({'s': df['ssn']})",
    "print(df['ssn']); result_df = df",
    "result_df = df.copy(); result_df['x'] = df['customer_email']",
    "result_df = df.loc[:, ['id', 'ssn']]",
])
async def test_explicit_access_is_a_clear_error_not_a_value(src, code):
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], code)
    assert "error" in res, res
    assert "classified as sensitive" in res["error"], res["error"]
    assert "removed from `df`" in res["error"]
    _assert_clean(_dump(res))
    # non-leaky: no traceback, no paths, only the name the script itself used
    assert "Traceback" not in res["error"] and "/app" not in res["error"]


async def test_error_is_because_the_column_is_absent_not_a_string_scan(src):
    """The proof that this is structural: the script asks pandas whether the
    column exists and records the answer. No string scan could produce
    False here; only a frame the column is not in can."""
    code = ("result_df = pd.DataFrame({'has_ssn': ['ssn' in df.columns],"
            " 'has_email': ['customer_email' in df.columns],"
            " 'has_amount': ['amount' in df.columns], 'ncols': [len(df.columns)]})")
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], code)
    assert "error" not in res, res
    row = res["rows"][0]
    assert row["has_ssn"] is False and row["has_email"] is False
    assert row["has_amount"] is True and row["ncols"] == len(SAFE)


# ── Task 7: indirect / adversarial access ────────────────────────────────────

@pytest.mark.parametrize("code", [
    # enumerate what is there
    "result_df = pd.DataFrame({'c': list(df.columns)})",
    "result_df = pd.DataFrame({'c': [str(df.dtypes.to_dict())]})",
    "result_df = pd.DataFrame({'c': [str(list(df.keys()))]})",
    # dump everything in memory in every representation pandas offers
    "result_df = pd.DataFrame({'c': [str(df.to_dict())]})",
    "result_df = pd.DataFrame({'c': [df.to_string()]})",
    "result_df = pd.DataFrame({'c': [repr(df)]})",
    "result_df = pd.DataFrame({'c': [str(df.values.tolist())]})",
    "result_df = pd.DataFrame({'c': [df.to_json()]})",
    "result_df = pd.DataFrame({'c': [str(df.describe(include='all').to_dict())]})",
    "result_df = pd.DataFrame({'c': [str(df.attrs), str(df.axes)]})",
    # try to find it by fuzzy name
    "result_df = pd.DataFrame({'c': [c for c in df.columns if 'ss' in c or 'mail' in c]})",
    "result_df = df.filter(like='ss')",
    "result_df = df.filter(regex='mail|ssn')",
    # melt / stack / transpose so column names become values
    "result_df = df.melt()",
    "result_df = df.T.reset_index()",
    "result_df = df.stack().reset_index()",
    # look at the namespace
    "result_df = pd.DataFrame({'c': [str(sorted(k for k in dir() if not k.startswith('_')))]})",
])
async def test_indirect_access_recovers_nothing(src, code):
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], code)
    if "error" in res:
        # a rejected script is acceptable -- as long as it leaks nothing
        _assert_clean(_dump(res))
        return
    text = _dump(res)
    _assert_clean(text)
    for col in FLAGGED:
        assert col not in text, f"{col} recoverable via: {code}"


async def test_reconstruction_from_other_columns_has_nothing_to_work_with(src):
    """Nothing in the safe columns correlates with the stripped ones; the
    only way to 'reconstruct' would be from memory the child never got."""
    code = ("import re\n"
            "joined = ' '.join(str(v) for col in df.columns for v in df[col].tolist())\n"
            "result_df = pd.DataFrame({'at_signs': [joined.count('@')],"
            " 'ssn_like': [len(re.findall(r'\\d{3}-\\d{2}-\\d{4}', joined))]})")
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], code)
    assert "error" not in res, res
    assert res["rows"][0] == {"at_signs": 0, "ssn_like": 0}


# ── Task 6: legitimate work is unaffected ────────────────────────────────────

async def test_legitimate_transformation_on_safe_columns(src):
    code = "result_df = df.groupby('region', as_index=False)['amount'].sum().sort_values('region')"
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], code)
    assert "error" not in res, res
    got = {r["region"]: r["amount"] for r in res["rows"]}
    assert got == {"east": 22.0, "north": 99.0, "west": 17.75}


async def test_clean_source_is_untouched(client, tmp_path, pickle_spy):
    _, tenant_id, _ = await _register(client)
    source_id = await _source(tenant_id, _csv(tmp_path, "id,product_name,amount,region",
                                               [(1, "Widget", 10.5, "west"), (2, "Gadget", 22.0, "east")]))
    res = await PythonRunner(tenant_id).run_on_source(source_id, "result_df = df")
    assert "error" not in res, res
    assert res["columns"] == ["id", "product_name", "amount", "region"]
    assert res["rows"][0]["product_name"] == "Widget"
    assert not any("withheld" in w for w in res["warnings"])
    assert b"product_name" in pickle_spy[0]


# ── Where the column list comes from ─────────────────────────────────────────

async def test_manual_override_to_none_releases_the_column(client, src):
    r = await client.put(f"/api/v1/sources/{src['source_id']}/classification",
                         headers={"Authorization": f"Bearer {src['token']}"},
                         json={"table": "main", "column": "ssn", "sensitivity": "none",
                               "reason": "test"})
    assert r.status_code == 200, r.text
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], "result_df = df[['id','ssn']]")
    assert "error" not in res, res
    assert res["rows"][0]["ssn"] == "512-34-6789"          # released, on purpose
    assert "customer_email" not in res["columns"]          # the other one still withheld


async def test_unprofiled_source_is_classified_on_the_spot(client, tmp_path, pickle_spy):
    _, tenant_id, _ = await _register(client)
    source_id = await _source(tenant_id, _csv(tmp_path), profile=False)
    res = await PythonRunner(tenant_id).run_on_source(source_id, "result_df = df")
    assert "error" not in res, res
    assert set(res["columns"]) == SAFE
    for v in LEAK_VALUES:
        assert v.encode() not in pickle_spy[0]


async def test_column_added_after_profiling_is_still_caught(src, pickle_spy):
    """The snapshot is stale: a `phone` column now exists in the file that
    the profiler never saw. Unknown-to-the-snapshot columns are classified
    on the spot, so staleness fails closed."""
    p = _csv(src["path"], HEADER + ",phone",
             [r + (f"+1 415 555 010{r[0]}",) for r in ROWS])
    async with tenant_session(src["tenant_id"]) as db:
        s = (await db.execute(select(DataSource).where(DataSource.id == src["source_id"]))).scalar_one()
        s.connection_config = {"file_path": str(p)}
        await db.commit()
    res = await PythonRunner(src["tenant_id"]).run_on_source(src["source_id"], "result_df = df")
    assert "error" not in res, res
    assert "phone" not in res["columns"] and set(res["columns"]) == SAFE
    assert b"555 010" not in pickle_spy[0]
    assert any("3 column(s) withheld" in w for w in res["warnings"])


async def test_run_on_dataframe_strips_on_the_spot_and_by_request(src, pickle_spy):
    df = pd.DataFrame([dict(zip(HEADER.split(","), r)) for r in ROWS])
    runner = PythonRunner(src["tenant_id"])
    res = await runner.run_on_dataframe(df, "result_df = df")
    assert "error" not in res, res
    assert set(res["columns"]) == SAFE
    for v in LEAK_VALUES:
        assert v.encode() not in pickle_spy[0]
    # a caller that knows more can withhold more
    res = await runner.run_on_dataframe(df, "result_df = df", sensitive_columns=["region"])
    assert set(res["columns"]) == SAFE - {"region"}
    assert b"west" not in pickle_spy[1]
    # and the original frame passed in is not mutated
    assert "ssn" in df.columns


# ── The API and tool paths carry the same frame ──────────────────────────────

async def test_endpoints_and_tool_see_stripped_frame(client, src):
    h = {"Authorization": f"Bearer {src['token']}"}
    for path in ("/api/v1/transformations/run/pandas", "/api/v1/transformations/preview/pandas"):
        r = await client.post(path, headers=h, json={"source_id": src["source_id"], "code": "result_df = df"})
        assert r.status_code == 200, (path, r.text)
        assert set(r.json()["columns"]) == SAFE
        _assert_clean(r.text)
        assert "masked_columns" not in r.json()     # nothing left for Item #10 to mask
    r = await client.post("/api/v1/transformations/run/pandas", headers=h,
                          json={"source_id": src["source_id"], "code": "result_df = df[['ssn']]"})
    assert r.status_code == 400 and "classified as sensitive" in r.json()["detail"]
    _assert_clean(r.text)

    from agent.tools.transformation_tools import run_python_transform
    res = await run_python_transform.ainvoke({
        "tenant_id": src["tenant_id"], "user_id": src["user_id"], "session_id": str(uuid.uuid4()),
        "source_id": src["source_id"], "script": "result_df = df",
    })
    assert set(res["columns"]) == SAFE
    _assert_clean(_dump(res))
