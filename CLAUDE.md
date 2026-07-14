# CLAUDE.md — AXIOM DataOps Agent

**Read this file in full before doing any work in this repo.** It is the living contract for how Claude Code operates here. Update it (Status Table + Known Gotchas, at minimum) in the same commit as any fix, feature, or discovery that changes what's true below.

Repo root: `c:\Pratyaksh Personal\My Projects\ai workforce\`. The one real project inside it is `dataops-agent/` — "AXIOM", an autonomous AI DataOps agent (part of the "AI Workforce Systems" product line). Everything else at repo root (`employee_data.csv`, `sales_data.csv`, `pipeline_config.json`, `tree.txt`, `generate_dataops_project.py`, `Document/*.pdf`) is scaffolding/sample/reference material, not application code. `generate_dataops_project.py` is the original scaffold generator that wrote out `dataops-agent/` — treat it as historical, not as the source of truth; the files it once generated have since been hand-edited (see patch scripts in Archive).

This repo has **zero git commits** — everything currently in `git status` is staged for an initial commit. Be extra careful with `git reset`/`git clean` until that first commit lands, since "discard uncommitted work" and "discard everything" are currently the same operation.

---

## 1. Architecture Summary

**Stack:** FastAPI (async, Python 3.11/3.13) + SQLAlchemy 2.0 async + PostgreSQL 16 + Redis + Celery (worker + beat) + LangGraph/LangChain agent (Gemini 2.0 Flash primary, Llama 3.3 70B via Groq fallback) + Next.js 15/React 19 frontend (source present but incomplete — see §2).

**Services** (`dataops-agent/docker-compose.yml` and `backend/docker-compose.yml` — two near-duplicate compose files exist, see Gotchas):
- `backend` — FastAPI app (`backend/main.py`), port 8000, mounted as a live volume (`./backend:/app`) so container edits are picked up without rebuild.
- `postgres` — Postgres 16-alpine, port 5432, db `dataops`.
- `redis` — Redis 7-alpine, port 6379. DB 0 = general cache, DB 1 = Celery broker, DB 2 = Celery result backend (`config.py`).
- `celery_worker` / `celery-worker` — runs `celery -A services.celery_app worker --concurrency=4`.
- `celery_beat` / `celery-beat` — runs the periodic scheduler (static + dynamically-registered per-pipeline schedules).
- `frontend` — **commented out** in root `docker-compose.yml`. Not started by `docker compose up` even if the source existed and built.

**Core end-to-end flow (chat → agent → tool → approval):**
1. Client calls `POST /api/v1/chat/` (JWT-authed) or connects to `WS /ws/chat/{tenant_id}/{session_id}` (⚠️ **unauthenticated**, see §2/§3).
2. `agent/dataops_agent.py` runs a LangGraph `StateGraph`: `inject_system` → `agent` (LLM bound to all tools via `.bind_tools`) → `approval_gate` → conditionally `tools` (a stock `ToolNode`) → loops back to `agent`, or `END`. Hard cap of 20 iterations, no config knob.
3. `personality.py` supplies the system prompt per `PersonalityMode` (engineer/founder/analyst/auditor) and gates tool calls per `OperationMode` (advisory/assisted/autonomous/audit) via `requires_approval()`, which checks a hardcoded `RISK_ACTIONS` risk table (low/medium/high).
4. If a tool call requires approval, `approval_gate_node` blocks it and injects an "Approval Required" message into the chat — but (see Gotchas) this in-graph gate is **not the same system** as the DB-backed approval queue read by `GET/POST /api/v1/approvals`.
5. The real, DB-backed approval workflow lives in `modules/governance/policy_engine.py` (`PolicyEngine`): a request is created, an admin/owner calls `POST /approvals/{id}/approve`, which calls `execute_approved_action()` → looks up the action in a hardcoded `TOOL_REGISTRY` dict → dynamically imports and invokes the real function via `importlib`.
6. Tool implementations live in `agent/tools/*.py`, one file per domain (ingestion, transformation, quality, orchestration, observability, governance, reporting, cicd), and call into `modules/*` for the actual work.

**Data model & tenancy:** Postgres, 17 SQLAlchemy models across `models/all_models.py` (13 models: Tenant, User, DataSource, Pipeline, PipelineRun, QualityRule, Incident, LineageNode, LineageEdge, AuditLog, ApprovalRequest, ChatMessage, DataContract, UsageMetric, KpiValue) and `models/cicd.py` (3 models: PipelineCommit, PipelineDeployment, CICDIncident). This is **multi-tenant by convention, not by enforcement**:
- Every model except `Tenant` carries a `tenant_id` column, but only `User`, `DataSource`, and `Pipeline` make it a real FK to `tenants.id` — the other 13 use a bare `String` with no FK constraint.
- Tenant scoping is entirely manual: `get_current_user()` decodes the JWT and returns `tenant_id` straight from client-supplied claims (no DB re-check); every endpoint/manager class is individually responsible for adding `.where(Model.tenant_id == tenant_id)`. There is no base query class, no session-level hook, no middleware, and **no Postgres RLS** (`create_enums.sql` only defines enum types).
- Spot-checked call paths (`dag_manager.py`, `policy_engine.py`, `run_tracker.py`, `rule_engine.py`, `connector_manager.py`, `schema_profiler.py`, `sql_runner.py`, all of `api/v1/`) do filter correctly today. The invariant holds only as long as every future query remembers to add the filter — nothing in the framework enforces it. Treat "did you scope this query by tenant_id?" as a mandatory review question for every new query in this codebase.

**Background jobs (Celery):** static beat schedule in `services/celery_app.py` — freshness check every 15 min (real), anomaly detection hourly (stub, logs only), daily reports every 24h (stub, logs only), CI/CD post-deploy health check every 60s (real). `modules/orchestration/scheduler.py` additionally injects **dynamic per-pipeline schedules** into `celery_app.conf.beat_schedule` at runtime, parsed from each pipeline's `schedule_cron` via a hand-rolled cron parser (not `croniter`, despite `croniter` being a dependency). Pipeline "DAG" execution (`modules/orchestration/dag_manager.py`) is **not actually a DAG** — no step graph, no topological sort; a "run" is a fixed linear sequence (sync source → run quality checks → mark result).

---

## 2. Status Table

### ✅ Done and verified (real implementation, exercised or clearly wired end-to-end)
| Area | What | How verified |
|---|---|---|
| Auth | Register/login/JWT (`api/v1/auth.py`) | bcrypt hashing w/ 72-byte truncation, HS256 JWT with `sub`/`tenant_id`/`email`/`role`/`exp`; `test_register_and_login` exercises register→login round trip |
| Core CRUD API | sources, pipelines, quality, incidents, governance, analytics, approvals, transformations, cicd | 40+ endpoints read directly in `api/v1/*.py`, all tenant-scoped via JWT except cicd webhook |
| Agent chat loop | LangGraph graph in `agent/dataops_agent.py` | read in full; graph wiring (inject_system→agent→approval_gate→tools) confirmed |
| LLM fallback | `services/llm_service.py` `get_llm_for_agent()` | uses LangChain `.with_fallbacks()`, Gemini→Groq, confirmed routing fix (see Archive) is in place |
| Ingestion connectors | postgres, mysql, csv, file, api, gsheets (`modules/ingestion/connectors/`) | real drivers (asyncpg, pymysql/aiomysql, pandas/pdfplumber/python-docx, httpx, gspread+google-auth real OAuth) |
| Quality rule engine | `modules/quality/rule_engine.py` | real evaluators for not_null/unique/accepted_values/range/regex/row_count/custom_sql against live data |
| Observability | `modules/observability/monitor.py`, `anomaly_detector.py`, `incident_manager.py` | real DB-aggregate freshness/health metrics; real statistical anomaly baselines; real LLM-powered incident triage via `LLMService.complete()` |
| Governance | `audit_trail.py`, `lineage_tracker.py` (real BFS graph traversal), `policy_engine.py` approve/reject/execute flow | read in full, DB-backed, dynamic dispatch via hardcoded (non-attacker-controlled) `TOOL_REGISTRY` |
| Reporting | `notification_service.py` (real Slack webhook + SMTP email), `report_generator.py` (real role-based reports) | read in full, no stubs |
| SQL sandboxing (safe path) | `modules/transformation/sql_runner.py` | `BLOCKED_KEYWORDS`, SELECT/WITH/EXPLAIN-only, parameterized `text()` execution, LIMIT injection, row cap |
| CI/CD pipeline | webhook → `cicd_service` → `cicd_tasks.run_ci_pipeline` (4 checks, risk scoring) → auto-deploy or approval gate; post-deploy monitor + auto-rollback | read in full across `services/cicd_*.py` |
| Test suite (auth + smoke only) | `backend/tests/test_api.py`, 9 tests | health check, docs availability, 6 "requires auth → 401" checks, register/login round trip, one validation-rejection test |

### 🔴 Known-broken
| Area | What's broken | Evidence |
|---|---|---|
| **WebSocket chat auth** | `WS /ws/chat/{tenant_id}/{session_id}` (`main.py:141-181`) takes `tenant_id` straight from the URL path with **no JWT verification** — anyone can connect as any tenant. This is the most severe issue in the codebase. | Read in full; no `Depends(get_current_user)` or token check on the WS route, unlike every REST endpoint |
| **Frontend can't build** | `frontend/src/lib/api.ts` and `frontend/src/lib/store.ts` are imported by `chat/page.tsx`, `dashboard/page.tsx`, `login/page.tsx` but **don't exist anywhere** — not on disk, not in the git index | Verified directly: `git ls-files dataops-agent/frontend` lists pages but not `lib/api.ts`/`lib/store.ts` |
| **Frontend directory missing from working tree** | `dataops-agent/frontend/` doesn't exist on disk at all, only as staged blobs in the git index (`git show :dataops-agent/frontend/...` works, `ls` doesn't) | Verified: `ls dataops-agent/frontend` → No such file or directory; `git ls-files` returns 11,544 entries under it |
| **node_modules + .next committed** | The git index has 11,446 `node_modules/` files and 84 `.next/` build-artifact files staged for the frontend, because `dataops-agent/.gitignore` is a pure-Python gitignore.io template with zero Node/Next.js entries | Verified: `git ls-files dataops-agent/frontend \| grep -c node_modules/` → 11446 |
| **`request_approval` tool is broken** | `governance_tools.request_approval` calls `PolicyEngine(tenant_id).request_approval(...)`, but `PolicyEngine` has no such method — the real method is `create_request(...)`. Calling this tool raises `AttributeError` at runtime. | `agent/tools/governance_tools.py:37-41` vs `modules/governance/policy_engine.py:65-72` |
| **In-graph approval gate doesn't persist to DB** | `approval_gate_node` in the LangGraph agent only mutates in-memory `pending_approvals` state — it never calls `PolicyEngine.create_request()`. Approvals surfaced mid-chat never appear in `GET /api/v1/approvals`, the queue the approvals API actually reads. | `agent/dataops_agent.py:55-67` — no DB write in this node |
| **`approval_executor.py` is dead/orphaned** | Defines `execute_tool_call()` but is never imported or called anywhere in the backend | Repo-wide grep, zero call sites outside its own definition |
| **Scheduled pipeline runs are argument-mismatched** | Celery beat fires `services.tasks.execute_pipeline_run` with `[pipeline_id, tenant_id]` (2 args, `scheduler.py:92-97`), but the task signature requires `(run_id, pipeline_id, tenant_id)` (3 args, `tasks.py:13`) — the manual/API trigger path (`DAGManager.trigger_run`) pre-creates the `PipelineRun` row and passes `run_id` correctly, but the *scheduled* path bypasses that and looks broken | `tasks.py:13` vs `scheduler.py:92-97` — not runtime-verified, flagged from static read; **first thing to confirm/fix if scheduled runs are reported failing** |
| **CI/CD deployment approve/reject has no role check** | `POST /cicd/commits/{id}/approve` and `/reject` (`cicd.py:228-292`) enforce tenant scoping but, unlike `approvals.py`, do **not** check `role in ("admin","owner")` — any authenticated tenant member can approve/reject production deployments | `api/v1/cicd.py:228-292` — inconsistent with `approvals.py:61,99` which does check role |
| **CI/CD webhook tenant spoofable if unconfigured** | `POST /cicd/webhook` is gated only by an optional HMAC signature (`GITHUB_WEBHOOK_SECRET`); if that env var is unset, the endpoint trusts a client-supplied `X-Tenant-ID` header/query param verbatim | `api/v1/cicd.py:130-132` |
| **`test_runner.py` (`QualityTestRunner`) is a no-op stub** | Every `_check_*` method unconditionally returns `"passed": True` without inspecting data. Not wired into the real quality-check path (`rule_engine.py`/`business_rules.py` are what's actually used) — but if anything ever calls `QualityTestRunner` expecting real checks, it will silently lie | `modules/quality/test_runner.py:37-53` |
| **`update_contract` approval is a no-op** | `TOOL_REGISTRY["update_contract"]` maps to `_noop()`, which just echoes kwargs back — approving this action type does nothing real | `modules/governance/policy_engine.py:38, 398-400` |
| **Migration/model drift on incident status enum** | `db3efa7d4d82_add_cicd_incidents.py` creates Postgres enum `incidentstatus` as lowercase 3-value `('open','investigating','resolved')`, but `models/cicd.py` declares the Python-side enum as uppercase 4-value `('OPEN','INVESTIGATING','RESOLVED','SUPPRESSED')` | `migrations/versions/db3efa7d4d82_add_cicd_incidents.py:22` vs `models/cicd.py:69-72` |
| **Missing migrations for 2 of 3 CI/CD tables** | `pipeline_commits` and `pipeline_deployments` (`models/cicd.py:76,103`) are never `CREATE TABLE`'d by any Alembic migration — only `cicd_incidents` is added by `db3efa7d4d82`, which assumes `pipeline_deployments` already exists. Schema setup for these apparently depends on running `create_enums.sql` manually, out-of-band from `alembic upgrade head` | Both migration files read in full; grep confirms no other migration creates these tables |
| **`ENABLE_AUTONOMOUS_MODE` / `ENABLE_DESTRUCTIVE_ACTIONS` are dead config** | Defined in `config.py`/`.env.example`, never read anywhere else in the backend. Actual autonomy gating is entirely `personality.requires_approval()`'s risk table, independent of these flags | Repo-wide grep, zero call sites beyond definition |
| **`SYNC_DATABASE_URL` is dead config** | Declared in `config.py`/`.env.example`; only Alembic uses a sync engine, and it builds its own URL by string-replacing `DATABASE_URL`, not from this setting | `migrations/env.py:21-26` |
| **Phantom high-risk tools** | `personality.RISK_ACTIONS["high"]` lists `delete_records`, `drop_table`, `modify_schema`, `revoke_access` as tool names — none of these are actually registered in `ALL_TOOLS`. The risk table references tools that don't exist. | `agent/personality.py:32` vs full read of `agent/tools/__init__.py` and all tool modules |
| **Duplicate/drifted docker-compose files** | `dataops-agent/docker-compose.yml` and `dataops-agent/backend/docker-compose.yml` both define the full stack with different container names (`dataops_backend` vs `dataops-backend`) and different health-check strategies (root version has no Postgres/Redis healthchecks, backend version does) | Both files read in full |
| **Celery beat has dead commented-out config** | A second `cicd-post-deploy-monitor` beat entry (300s interval) is commented out with a stray inconsistent comment | `services/celery_app.py:46-49` |

### ⚪ Not yet built
- Frontend beyond 4 pages (`/`, `/chat`, `/dashboard`, `/login`) — nav links to `/sources`, `/pipelines`, `/incidents`, `/quality`, `/governance` exist but those pages don't.
- Real anomaly-detection and daily-report Celery tasks (`services/tasks.py` — both explicitly commented `"""Placeholder — full implementation in Phase 3."""`).
- Any test coverage for: `agent/` (LangGraph graph, tools, personality gating), `modules/*` (all 6 module packages), `services/` (Celery tasks, LLM service, CI/CD services). Current suite (9 tests) only covers auth plumbing and a couple of smoke checks.
- Shared `require_role()` dependency (role checks are copy-pasted ad hoc per endpoint, and inconsistently — see cicd approve/reject above).
- Any tenant-scoping enforcement mechanism beyond "the developer remembered to add the filter."
- Token revocation/refresh for JWTs (no `iat`/`nbf`, no blocklist).

---

## 3. Known Gotchas

*This section only grows. Append; never delete. If a gotcha turns out to be fixed, mark it `[RESOLVED: <how/when>]` rather than removing it.*

- **Two docker-compose.yml files, not one.** `dataops-agent/docker-compose.yml` (root, referenced by the README quick-start) and `dataops-agent/backend/docker-compose.yml` both stand up the full stack independently, with different container/network names and different Postgres/Redis healthcheck behavior. Running both simultaneously will port-collide on 8000/5432/6379. Always confirm which one a command/doc is referring to before running `docker compose` commands.
- **The frontend service is commented out in the root compose file.** `docker compose up` never starts a frontend even after the missing files are restored — you must uncomment it in `dataops-agent/docker-compose.yml` first.
- **`.gitignore` in this repo only covers Python.** It's a stock gitignore.io Python template with no Node/Next.js section — `node_modules/`, `.next/`, and other JS build artifacts will get silently `git add`ed if you run a broad `git add -A`/`git add .` inside `dataops-agent/frontend/`. Before ever committing frontend work, add a `node_modules/`, `.next/`, `out/` block to the gitignore first, and double check `git status` doesn't show thousands of new files.
- **JWT tenant_id is trusted, never re-validated against the DB.** `get_current_user()` just decodes the token. If you ever add a "deactivate tenant" or "remove user from tenant" feature, remember that a previously-issued JWT for that user/tenant stays valid until it expires — there's no revocation.
- **Tenant scoping is a per-query convention, not a framework guarantee.** Every new query against a tenant-owned table must manually add `.where(Model.tenant_id == tenant_id)`. There is no base repository/query class to inherit this from. When reviewing or writing any new DB query in this codebase, explicitly check for the tenant filter — it is the single easiest way to introduce a cross-tenant data leak here.
- **Two different LLM fallback mechanisms coexist.** `services/llm_service.py` has both `get_llm_for_agent()` (LangChain `.with_fallbacks()`, used by the actual agent graph) and `invoke_llm()` (manual tenacity-retry + manual fallback, apparently unused by the graph). Don't assume changing one changes the other's behavior.
- **Ingestion connectors expose a raw `execute_sql()` that bypasses `SqlRunner`'s safety layer.** `SqlRunner` (the safe, keyword-blocked, parameterized path) is one specific caller; `postgres_connector.py` and `mysql_connector.py` both independently expose `execute_sql()` methods that run arbitrary SQL with no keyword filtering. If you add a new caller, go through `SqlRunner`, not the connector directly, unless you've deliberately re-derived the same protections.
- **`python_runner.py`'s in-process `exec()` sandbox is intentionally not airtight.** It AST-allowlists imports/names and uses a restricted builtins namespace + thread timeout, but the code's own docstring says this is "sufficient" only for already-LLM-validated code, not untrusted input, and recommends a real microVM (gVisor/Firecracker) for anything stronger. Don't expose this path to raw user-submitted Python without adding real process isolation first.
- **Debug/patch scripts in `backend/` root are leftover hotfixes, not part of the app.** `diagnose.py`, `fix_analytics.py`, `fix_analytics2.py`, `patch_analytics.py` were run manually inside the container (they hardcode the `/app/...` container path) to patch a `NoneType has no attribute 'value'` crash in `/api/v1/analytics/pipelines` caused by NULL pipeline-status rows in a groupby. The underlying fix should already be reflected in `api/v1/analytics.py` itself — if you're debugging analytics and considering writing a new one-off patch script, first check whether `analytics.py` already has the fix these scripts describe, and prefer fixing it in place over adding another patch script to the pile.
- **Test suite hits whatever DB `APP_ENV=test` resolves to — there's no isolated test DB or per-test reset.** `conftest.py` builds an `AsyncClient` against the real `main.app` with no fixture-level DB setup/teardown. Running tests repeatedly can accumulate rows (e.g. from `test_register_and_login`). Don't assume test runs are hermetic.
- **`RISK_ACTIONS["high"]` names tools that don't exist** (`delete_records`, `drop_table`, `modify_schema`, `revoke_access`). If you're asked to "make destructive actions require approval," check whether the actual mutating tool (e.g. `execute_sql_transform`, `resolve_incident`) is even in that risk table before assuming the gate already covers it — right now, most real mutating tools default to whatever risk tier `get_risk_level()` falls back to, not `"high"`.
- **Approvals created mid-chat (via the LangGraph `approval_gate_node`) do not show up in the `/api/v1/approvals` queue.** Only approvals created through `PolicyEngine.create_request()` (e.g. via `seed_approval.py` or a correctly-written tool) persist to the DB. If a user reports "the agent said it needs approval but I don't see it in the approvals list," this is why — check whether the code path that created it actually called `create_request()`.
- **Celery beat's scheduled pipeline-run task call looks arg-mismatched** (see Status Table). Don't assume scheduled pipelines are exercising the same code path as manually-triggered ones until this is confirmed/fixed.
- **`RunTracker` is a pass-through, not a separate system.** It exists only "for agent tool compatibility" (per its own comment) and just delegates to `DAGManager`. Don't look for run-tracking logic there — it's in `dag_manager.py`.
- **There is no real DAG.** Despite the name `DAGManager` and the module path `modules/orchestration/`, pipeline execution is a fixed linear sequence (sync → quality check → done), not a graph with dependency resolution. If a task asks you to add a new pipeline step, you're inserting into a linear chain in `tasks.py`'s `_execute_run`, not registering a DAG node.

---

## 4. Workflow Rules

These govern how any Claude Code session (including this one) operates on this repo:

1. **Read this file in full at the start of every session before taking any action.**
2. **Work one issue or feature per session.** Verify each fix against the real running system (start the stack, hit the actual endpoint/flow, don't just eyeball the diff) before moving to the next one. Don't batch multiple unverified changes together.
3. **If verifying a fix surfaces a new or hidden related bug, resolve it in the same session** rather than stopping at the original scope — but still commit it separately (see rule 5).
4. **For any non-trivial feature or architectural change, propose the approach and tradeoffs first and wait for approval before writing code.** This includes anything touching tenant isolation, auth, the approval workflow, or the Celery scheduling mismatch — these are exactly the areas where a quick fix can silently reintroduce one of the gotchas above.
5. **Write or update a regression test alongside every bug fix, in the same commit.** Given current test coverage (auth + smoke only), most fixes in `agent/`, `modules/`, or `services/` will be the first test for that code path — that's expected, not a sign you're doing extra work.
6. **Commit after every individually verified fix**, with a message describing the issue and how it was verified. Don't batch multiple fixes into one commit.
7. **Update this file's Status Table and Known Gotchas section as part of the same commit** whenever something is fixed, added, or newly discovered. Move superseded information into the Archive below rather than deleting it.
8. Given there are no commits yet in this repo, the first commit is an unusually large diff — that's expected, but subsequent commits should follow the one-fix-per-commit rule above.

---

## Archive

*Superseded information kept for history — do not delete, append new superseded items here as they arise.*

- **LLM fallback routing bug (fixed, pre-dates this document).** `services/llm_service.py` previously had `get_fallback_llm` always constructing a `ChatGroq` client regardless of the configured `FALLBACK_LLM_MODEL`. An inline comment at `llm_service.py:35-39` notes this was fixed to route via `_build_llm(settings.FALLBACK_LLM_MODEL, ...)`, matching whatever model name is actually configured.
- **Prior CLAUDE.md content:** none — the file was empty (0 bytes) before this rewrite. This is the first substantive version.
- **`README.md` claims frontend is "(Coming soon)"** (`dataops-agent/README.md` Architecture section) — this is stale. Frontend source exists (partially — see Status Table "Known-broken") and was staged into git, it's just not present on disk in the current working tree and can't build due to missing `lib/api.ts`/`lib/store.ts`. Treat the README's tech-stack and API-endpoint tables as directionally correct but not exhaustive; the endpoint table in this file's Architecture Summary supersedes it for anything not listed there — see the full per-file agent reports that produced this document for the complete endpoint list (chat, uploads, sources, pipelines, quality, incidents, governance, approvals, analytics, transformations, cicd — ~40+ routes total, README only lists 9).
