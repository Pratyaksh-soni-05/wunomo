# Product Status Audit — 2026-08-18

**Method:** read-only reconnaissance. Nothing in this document was fixed or committed as code — the only change made alongside this report is this file itself plus new numbered entries in `docs/context/WALKTHROUGH_FINDINGS_2026-08.md` (items 33–44) for bugs found while gathering evidence. Every `[x]` below cites a specific test name, commit hash, or dated live-verification passage — not a doc's own say-so. Where a doc claims something is done and no independent evidence could be found (or the evidence contradicts the claim), it's marked `[?]` and said so explicitly, per the standard this audit was commissioned to hold everything else to.

**Sources cross-checked:** `CLAUDE.md`, `docs/context/{WUNOMO_MASTER_CONTEXT,ENGINEERING_HISTORY,WORKFLOW_RULES,GOTCHAS,SESSION_LOG,STATUS_TABLE,WALKTHROUGH_FINDINGS_2026-08}.md`, `docs/PRODUCT_AUDIT.md` (2026-08-04 — an earlier, independent, code-read-first audit; treated as a prior claim to re-verify, not as ground truth), `docs/PRODUCT_STATUS.md` (2026-07-24, the oldest and most superseded of the three), plus direct reading of `backend/api/v1/*.py`, `backend/agent/tools/*.py`, `backend/modules/*`, `frontend/src/app/**`, and three parallel research passes (backend endpoints, frontend routes, AXIOM tools) each independently re-deriving evidence from the same source-of-truth files rather than trusting a doc's summary of itself.

**A load-bearing finding before anything else:** `docs/PRODUCT_AUDIT.md`, dated 2026-08-04, is a prior, independent, comparably rigorous audit that predates the entire Item 6 Tasks feature (built 2026-08-05 through 08-12) and the argument-resolution work (08-16/17). Its single biggest finding — "AXIOM mostly analyzes and reports rather than acting, because every turn is bounded by one synchronous HTTP request" — has since been substantially addressed by Tasks. Its other ~20 ranked findings were checked one by one against current code during this pass: **most are still true, unfixed, exactly as documented two weeks ago.** Several are logged here for the first time as WALKTHROUGH_FINDINGS items (33–37) specifically because they'd never made it into that tracker despite being real and known.

---

## Phase 1 evidence — raw results

**Backend test suite** (`docker compose exec backend python -m pytest tests/ -v`): **398 passed, 1 deselected, 0 failed** (752.75s). The deselected test (`test_real_live_llm_generates_a_valid_reviewable_plan`) was then run separately per the zero-cost-quota-check protocol:
- **Quota check before spending anything**: `SELECT provider, count(*) FROM llm_usage_events WHERE created_at >= CURRENT_DATE` → `gemini: 1` (the one known-synthetic row `test_log_llm_usage_persists_a_real_row` always writes) — **real spend before the live_llm run: 0**.
- `pytest tests/ -m live_llm`: **1 passed** (15.42s, real Gemini call, no fallback). **Total suite: 399/399, 0 failures. Total real LLM spend today: 1 call.**
- One test (`test_notification_wiring.py::test_freshness_check_notifies_once_per_newly_stale_source_not_every_tick`) is a documented, pre-existing, order/state-dependent flake (`STATUS_TABLE.md` Known-broken row) — did not reproduce in this run's full-suite pass.

**Frontend** (`frontend/`):
- `npx tsc --noEmit`: **clean, 0 errors.**
- `npm run build`: **clean, 0 errors, 0 warnings**, exit 0. 26 routes compiled (25 static + `/tasks/[id]` dynamic). This is also the authoritative route list used in Section 2 below.

**Hard rules cross-check** (CLAUDE.md's 4), checked against current code directly, not carried forward from any doc:

| # | Rule | Status | Evidence |
|---|---|---|---|
| 1 | No Postgres connections outside `postgres_connector.py` | **Still violated, unchanged** | 3 stray connectors confirmed via grep: `modules/ingestion/schema_profiler.py:84`, `modules/transformation/python_runner.py`, `modules/transformation/sql_runner.py` all call `asyncpg.connect()` with a hand-built DSN. `postgres_connector.py:10` uses `c['host']` (no default) correctly. No 4th stray connector found (`services/cicd_monitor.py`'s `create_async_engine(settings.DATABASE_URL)` connects to the app's *own* DB, not a source's — not the same class of violation). |
| 2 | `get_primary_llm()`/`get_fallback_llm()` never unconditionally `ChatGoogleGenerativeAI` | **Holds** | Exactly one `ChatGoogleGenerativeAI(` construction site in the entire backend (`services/llm_service.py:122`), inside `_build_llm()`, which branches on model name. |
| 3 | Never write a tz-aware `datetime.now(timezone.utc)` into a naive column | **Holds** | Every raw (non-`.replace`) call site checked individually: all are either `models/cicd.py`'s deliberately tz-aware columns (`trigger_time`, `resolved_at`, `deployed_at`, `rolled_back_at`, `completed_at` on `PipelineCommit`/`PipelineDeployment`/`CICDIncident`), a non-DB `.isoformat()` string build (`agent/dataops_agent.py:308`), or subsequently `.replace(tzinfo=None)`-stripped before use (`quota_service.py:87-88`). |
| 4 | Never default a source's `host` to `"localhost"` | **Still violated, unchanged** | `modules/transformation/python_runner.py:419` and `modules/transformation/sql_runner.py:223,269` both still do `config.get("host", "localhost")`. |

**Other direct findings gathered before the checklists below** (not from any doc, verified live against current code 2026-08-18):
- **17 commits unpushed to `origin/master`** (`git log --oneline origin/master..HEAD | wc -l` → 17) — worse than the 14 documented 2026-08-12. Nothing this project has built since 2026-08-12 exists anywhere but this one machine.
- **No CI pipeline exists** — `.github/workflows/` does not exist.
- **Credential rotation still not done** — `POSTGRES_PASSWORD` is still the literal 8-character default `changeme`; `JWT_SECRET` is still 9 characters (a placeholder length, not a real rotated secret). Both flagged as urgent in `WUNOMO_MASTER_CONTEXT.md` §6 on 2026-08-12; unchanged.
- **`ENABLE_AUTONOMOUS_MODE`/`ENABLE_DESTRUCTIVE_ACTIONS`** (`config.py:33-34`) are declared but referenced nowhere else in the codebase — dead config, not wired to anything. Not a security hole (nothing depends on them being `False`), but worth knowing they don't actually gate anything despite reading like safety flags.
- **Anomaly-detection and daily-report Celery tasks are still literal placeholders** (`services/tasks.py:335,346`, `"""Placeholder — full implementation in Phase 3."""`) — matches `STATUS_TABLE.md`'s "Not yet built" list, itself last touched long enough ago that its own "current suite: 9 tests" line is badly stale (the real count is 399) — a reminder that even this project's own "not yet built" list needs spot-checking, not blanket trust.

---

## 1. Backend — by API segment

Format: `[x]` test-covered (test file:function cited) · `[x — manual]` no automated test, but a specific dated live-verification passage exists (quoted/cited) · `[?]` claimed somewhere but no evidence found, or the evidence is stale/contradicted · `[ ]` no test, no citation, never exercised. Full per-endpoint detail (121 endpoints) comes from a dedicated research pass cross-referencing `backend/api/v1/*.py` against `backend/tests/*.py` and `STATUS_TABLE.md`/`SESSION_LOG.md`.

### Health
- [x] `GET /health` — `test_api.py::test_health`
- [ ] `GET /health/db` — no test; only named as an existing URL in `WUNOMO_MASTER_CONTEXT.md:171`, not a verification claim.

### Auth (9 endpoints)
- [x] `POST /register`, `POST /login`, `POST /email-code/request`, `POST /email-code/verify`, `GET /google/login-url`, `POST /google/callback`, `POST /resolve-workspace`, `GET /me`, `PATCH /me` — all test-covered (`test_password_login_disambiguation.py`, `test_email_code_auth.py`, `test_google_oauth.py`, `test_theme_persistence.py`, used as fixtures throughout). This is the best-tested segment in the backend.
- **Gap not visible in endpoint coverage**: password login has **zero rate limiting or lockout** (Finding 38) — every endpoint above is "covered" in the sense of being exercised, but none of that coverage tests brute-force resistance, because none exists to test.

### Sources (9 endpoints)
- [x] `GET /`, `POST /` — `test_api.py`, `test_contract_service.py`, `test_permission_matrix.py`
- [x — manual] `DELETE /{id}` — automated coverage only reaches the `nonexistent-id` 403/404 path (`test_rbac.py:122`); real-delete success path cited only in `STATUS_TABLE.md:61` ("Sources (create/sync/profile/delete)... Live-verified per screen via Playwright... real action side-effects").
- [x — manual] `POST /{id}/profile`, `POST /{id}/sync` — same pattern: only permission-gate automated tests exist; success path cited in `STATUS_TABLE.md:61,77` ("Sync Metadata's real effect confirmed via the Last Profiled timestamp genuinely advancing").
- [ ] `GET /{id}`, `PUT /{id}`, `GET /{id}/preview`, `POST /{id}/drift` — no test, no doc citation anywhere.

### Pipelines (11 endpoints)
- [x] `GET /`, `POST /`, `DELETE /{id}`, `POST /{id}/trigger`, `POST /{id}/activate`, `PUT /{id}/schedule` — `test_pipeline_delete.py`, `test_scheduled_pipelines.py`, `test_quota_enforcement.py`, `test_rbac.py`.
- [x — manual] `POST /{id}/pause`, `GET /{id}/runs` — no automated test; cited in `STATUS_TABLE.md:61,83` ("real action side-effects (status transitions...)"; "watched 3 real, successful, correctly-timed runs land").
- [ ] `GET /{id}`, `PUT /{id}`, `POST /{id}/backfill` — no test, no doc citation.
- [ ] `GET /api/v1/runs/{pipeline_id}` (separate router, `runs.py`) — **Finding 41**: appears to be a dead, duplicate route shadowing the same concept via a different, apparently-unused manager (`RunTracker` vs. the real `DAGManager`). No test, no citation, no evident caller.

### Quality (4 endpoints)
- [x] `POST /` — `test_pipeline_delete.py`
- [x — manual] `DELETE /{id}` — permission path only automated (`test_rbac.py:134`); real-delete cited in `STATUS_TABLE.md:61`.
- [x — manual] `POST /{pipeline_id}/run` — permission path only automated; genuine functional tests (`test_custom_sql_rule_safety.py`, `test_business_rules.py`) call `QualityRuleEngine.run_checks()` directly, bypassing this route entirely. Success path cited only in `STATUS_TABLE.md:61`.
- [ ] `GET /` — no test hits this directly, no doc citation.

### Incidents (5 endpoints)
- [x] `GET /`, `POST /` — `test_api.py`, `test_notification_wiring.py`
- [x — manual] `POST /{id}/resolve` — permission path only automated (`test_permission_matrix.py:67`); functional tests call `IncidentManager.resolve_incident()` directly. Cited via `STATUS_TABLE.md:61`.
- [ ] `GET /{id}`, `PUT /{id}` — no test, no citation.

### Governance (9 endpoints)
- [x] `GET /graph` — `test_lineage_sync.py` (5 tests), also live per `STATUS_TABLE.md:58` (a real tenant going from a stale 2-node to a real 9-node/5-edge graph).
- [x] `POST /contracts`, `POST /contracts/{id}/validate` — `test_contract_service.py` (real success + 404 cases), `test_permission_matrix.py`.
- [x — manual] `GET /audit` — no automated test; `STATUS_TABLE.md:61` names a specific fix-and-reverify ("both `contract.created` and `contract.validated` entries appear correctly after the fix").
- [ ] `GET /lineage/{asset_name}`, `POST /lineage/node`, `POST /lineage/edge`, `GET /contracts`, `GET /contracts/{id}` — no test, no specific citation (the `sync_tenant_lineage()` narrative names only `GET /graph`'s output, not `lineage/{asset_name}`'s).
- **[?] `validate_data_contract`'s underlying logic has a live, unfixed bug** — see Finding 34: every real validation against a genuinely profiled source reports every column missing. The "test-covered" checkmark above reflects the route being *reachable and exercised*, not that its output is *correct*.

### Approvals (5 endpoints)
- [x] `GET /`, `GET /merged`, `POST /{id}/approve` — `test_api.py`, `test_approvals_merged.py`, `test_approval_execution.py` (full HTTP round-trip, real DB side-effect asserted).
- [x — manual] — **not applicable to reject, see below.**
- [ ] `GET /{id}` — no test, no citation.
- **[?] `POST /{id}/reject`** — zero automated test. `STATUS_TABLE.md:52` asserts the card is "wired to real `POST /approvals/{id}/approve`/`reject`" but the live-verification narrative only names clicking **Approve**. This is exactly the "asserted-but-not-individually-verified" pattern this audit was built to catch.

### Analytics (8 endpoints) — worst test-coverage ratio in the backend
- [x] `GET /health`, `GET /recent-runs` — `test_api.py`, `test_analytics_recent_runs.py` (3 tests).
- [x — manual] `GET ""` (overview), `GET /quality` — no automated test; both cited in `STATUS_TABLE.md:52`'s Dashboard Playwright pass ("all 7 KPI values... render real data"; "two Chart.js trend charts... Verified live").
- [ ] `GET /pipelines`, `GET /kpis`, `POST /kpis`, `GET /usage` — no test, no citation anywhere. **5 of 8 endpoints in this segment (63%) have never been exercised by anything.**

### Transformations (9 endpoints)
- [x] `POST /run/sql`, `POST /run/sql/dry-run`, `POST /run/pandas`, `GET /runs` — `test_transform_run_log.py`, `test_transform_runs_list.py` (real success paths, real persisted rows).
- [x — manual] `POST /generate/pandas` — no test via this route (`test_transform_generator.py` tests the service directly); cited live in `STATUS_TABLE.md:77` ("a real Gemini call generated pandas code correctly referencing real column names").
- [ ] `POST /generate`, `POST /generate/sql`, `POST /preview/pandas`, `POST /explain` — only generic "wired to" build claims in `STATUS_TABLE.md:77`; never individually named as exercised.

### Catalog (1 endpoint)
- [x] `GET /` — `test_catalog.py` (5 tests), also live per `STATUS_TABLE.md:77`.

### CI/CD (12 endpoints) — worst absolute never-exercised count
- [x] `POST /commits/{id}/approve`, `POST /commits/{id}/reject` — `test_rbac.py` (both allow/deny cases against real commit IDs).
- [x — manual] `POST /webhook` — no direct automated test; `STATUS_TABLE.md:65` describes a genuinely specific, named, full end-to-end customer-simulation pass (webhook → risk-check → approval → deploy).
- [x — manual] `GET /commits`, `GET /deployments`, `GET /status/summary` — no test; covered only narratively by `STATUS_TABLE.md:61`'s screen-level Playwright pass.
- [x] `PATCH /incidents/{id}/resolve` — `test_rbac.py`, but only against `nonexistent-id` — **no automated test resolves a real `CICDIncident`.**
- [ ] `GET /commits/{id}`, `GET /deployments/{id}`, `POST /deployments/{id}/record-run`, `GET /deployments/{id}/health`, `GET /incidents` — no test, no citation. **6 of 12 endpoints never exercised at all; 10 of 12 have no automated test of any kind.**
- **This segment also carries three of PRODUCT_AUDIT.md's most severe findings, all re-confirmed still true 2026-08-18**: schema-drift check permanently no-ops (Finding 35), SQL static analysis never reads real diff content (Finding 40), and the auto-rollback monitor has no live trigger (Finding 40) — `record-run`, the endpoint that's supposed to feed it, has zero callers anywhere except tests calling it directly.

### Chat (3 endpoints)
- [x] all 3 — `test_api.py`, `test_chat_sessions.py`, `test_chat_approval_status_resolution.py`; also the entry point for the 3 real `COMPLETED` task runs on 2026-08-17.

### Onboarding, Team, Billing, Settings, API Keys, Tasks, Uploads
- [x] **All fully test-covered** — these are the best-built cluster in the backend, matching `PRODUCT_AUDIT.md`'s own characterization. Tasks in particular: every endpoint has both automated coverage and the 2026-08-17 live `COMPLETED`-run evidence.
- **[?] API Keys**: CRUD is real and well-tested, but **no endpoint anywhere accepts an API key as a request credential** — confirmed by reading every router's auth dependency; all resolve only through `get_current_user()` (JWT-only). Matches `CLAUDE.md`'s own "Not yet built" note — correctly documented as not-done, not a contradiction, just restated here as directly verified rather than assumed.
- [ ] `POST /uploads/` (the bare route, distinct from `/uploads/register`) — no test hits it directly.

**Segment summary** (from the dedicated 121-endpoint pass): **76 test-covered (63%), 24 manual-only (20%), 21 never exercised (17%)**. Worst ratios: Analytics (5/8 never exercised), Governance (4/9), Sources (4/9 plus 2 manual-only), CI/CD (6/12 never exercised, worst absolute count).

---

## 2. Frontend — by screen

All 26 routes from the clean `npm run build` output. **Zero routes have any automated test** — confirmed: `frontend/package.json` has no test framework (no Jest/Vitest/Playwright-as-test-runner/Cypress/RTL) and no `test` script; a repo-wide search for `*.test.tsx`/`*.spec.tsx` returns zero hits. Every `[x]` below is therefore `[x — manual]` by definition; the distinction that matters here is whether a *specific, dated, named* verification passage exists, versus generic "built and working" prose.

- [x — manual] `/` — `STATUS_TABLE.md:100-101` (both themes × both viewports, every link fetched and confirmed non-error, full rendered-text honesty audit). **[?]** `SELF_TEST_GUIDE.md` §1.3 says a fresh visitor to `localhost:3000` "should land on a login page" — the code unconditionally renders the marketing page instead (Finding 43, guide is stale, not the app).
- [x — manual] `/ai-employees` — `STATUS_TABLE.md:99` (full text-content audit, tile-count assertion, real navigation confirmed).
- [ ] `/analytics`, `/audit`, `/automations` — **confirmed stub pages** (`<StubPage>`, matches build's `0 B` bundle size, matches `SELF_TEST_GUIDE.md` §14's own "these are stub pages" admission). Not a verification gap — nothing real exists behind them to verify.
- [x — manual] `/api/auth/callback/google` — `STATUS_TABLE.md:46,49` (real consent-screen click-through, real token exchange).
- [x — manual] `/approvals`, `/catalog`, `/cicd`, `/dashboard`, `/governance`, `/incidents`, `/pipelines`, `/quality`, `/sources`, `/transforms` — all `STATUS_TABLE.md:61,52,77` etc., specific per-screen Playwright passes naming real interactions and real rendered data, not generic prose. **`/cicd` is absent from `SELF_TEST_GUIDE.md` entirely** (Finding 44) despite having real verified functionality.
- [x — manual] `/chat`, `/tasks`, `/tasks/[id]` — the most solid pages in the app; `SESSION_LOG.md` 2026-08-17's three real `COMPLETED` task runs are the strongest evidence in this entire audit (real mutations, real approval-gate screenshots, real DB confirmation).
- [x — manual] `/invite/accept`, `/login`, `/onboarding`, `/signup`, `/team` — full Playwright scripts named in `STATUS_TABLE.md:44,49,97`, including at least one named *negative* finding kept honest rather than hidden ("JWT-replay-after-removal... result: HTTP 200, access persists").
- [x — manual] `/settings` — `STATUS_TABLE.md:96`, two full scripts (owner + downgraded-viewer), including a real secrets-in-localStorage check.
- **[?] `/billing`** — the only citation on record (`STATUS_TABLE.md:98`, Phase 17) describes a plan-picker/upgrade UI that has since been **deleted from the shipped code** (Finding 42). The current read-only page has no verification event of its own. `docs/PRODUCT_AUDIT.md` independently flagged this same drift on 2026-08-04.
- [ ] `/_not-found` — unmodified default Next.js behavior, no custom code, not mentioned anywhere.

**Summary**: of 26 routes, 21 have specific, named, dated verification; 3 are confirmed stubs with nothing to verify; 1 (`/billing`) has a stale, inapplicable citation; 1 (`/_not-found`) is untouched framework default. **Zero have any automated regression test** — every one of the 21 "verified" screens is one Playwright script, run once, at a specific point in time, never re-runnable, never re-run since (confirmed directly, not inferred).

---

## 3. The AXIOM agent — tools, task shapes, resolution, approval gates

**40 registered tools**, all present in both `TOOL_CAPABILITIES` (rbac.py) and `RISK_ACTIONS` (personality.py) — the old "RISK_ACTIONS names tools that don't exist" gotcha **no longer holds**, guarded now by `test_every_risk_action_name_is_a_real_registered_tool`.

- [x] **6 of 40 tools (15%) have a genuine automated test** invoking the real `@tool`-wrapped function: `list_open_incidents`, `triage_incident`, `resolve_incident` (`test_incident_manager.py`), `execute_sql_transform`, `run_python_transform` (`test_transform_run_log.py`), `get_cicd_status` (`test_agent_graph.py`, full `run_agent()` path).
- [x — manual] **29 more have specific, dated, named live-run evidence** (real chat/task calls against real seeded tenants, real DB/API confirmation — not generic prose) — see the full per-tool table in the audit transcript for citations.
- **[?] 5 tools are genuinely unverified by both standards**: `ingest_file`, `preview_source_data`, `detect_schema_drift`, `backfill_pipeline` (no test, no individually-named live run), plus `get_lineage` (bundled into a blanket "all 5 tools" claim in `STATUS_TABLE.md:34` without being individually named — treated as insufficient per this audit's own standard).
- **Security-relevant misclassification (Finding 33)**: `detect_schema_drift` is tagged `low`/`"view"` (every role, no approval gate) but its real backing method **writes** `schema_snapshot`/`last_profiled_at` and commits. It is also the least-verified tool in the registry. No tool was found mutating at a tier *stricter* than warranted; two tools are the mirror-image (over-classified: `ingest_file` never writes to the DB despite being gated `medium`; `validate_business_rule`'s backing method never commits despite being gated `medium`).
- [x] `RISK_ACTIONS["high"]` is genuinely empty and that's now correct (no delete/drop/revoke-capable tool exists) — `test_high_tier_is_intentionally_empty_today` guards this.
- **Task shapes**: only **13 of 40 tools (32%)** are reachable through Tasks at all (`TASK_SHAPE_ALLOWED_TOOLS`, `task_planner.py`) — every other mutating tool (pipeline create/pause/schedule, transformation execute, contract create/validate, business-rule validate, alerts) is chat-only, unreachable by any planned/approved multi-step task.
- [x] **Argument resolution (findings 8/9/16/31/32)** — Tier 1 deterministic + Tier 2 LLM-adapt-with-never-guess-guardrail, live-verified 2026-08-17/18 across 5 real task runs including a forced, genuine, unrecoverable failure producing the honest error message. This is the single most rigorously live-verified subsystem in the entire product — see `SESSION_LOG.md`'s 2026-08-17 entry for the full run-by-run detail.
- **[?] Item 31's residual gap** (noted at the time, not new): `sync_profile_quality`'s own allowed-tools list has no pipeline-discovery tool — `run_quality_checks`'s `pipeline_id` can structurally never resolve to a real value in this shape, even after Finding 31's fix (which stops it from lying about success, but doesn't give it anything to succeed against). Still open.
- **[?] PRODUCT_AUDIT.md's "verify after acting" gap (its own item 4, "not started")** — re-checked: **now partially closed** by Item 6 stage 4's `VERIFYING`/`COMPLETED_WITH_UNCONFIRMED_STEPS` mechanism, but only for the 13 tools reachable via Tasks; a chat-only mutating tool (e.g. `run_pipeline` via direct chat) still gets no structural verify-after-act step — that gap is closed for Tasks, still open for chat.

---

## 4. Auth, roles, tenancy

- [x] **3 real auth methods** (password, Google OAuth, email-code), all live-verified with real consent screens / real delivered emails — `STATUS_TABLE.md:44,49`.
- [x] **RBAC enforced identically on REST and agent tool-calling** via one shared `TOOL_CAPABILITIES` map — `test_agent_role_gate.py`.
- [x] **Fresh per-request `is_active`/role re-check** for the REST path (`get_current_user()`) — Phase 19, tested.
- **[?] JWT revocation on role change/removal — contradicted between two of this project's own docs.** `docs/PRODUCT_STATUS.md` (2026-07-24) claims: "Removed/demoted users lose access on their *next request*, not just their next login... confirmed via SQL-echo capture." `docs/context/GOTCHAS.md` (later, Phase 17) directly contradicts this with a **live-reproduced counter-example**: "a JWT captured immediately before removal was replayed against `GET /team/members` afterward and returned a real `200`." The later, more specific, live-reproduced claim is almost certainly the accurate one — `get_current_user()` is a bare `jwt.decode()` with no DB lookup at all, confirmed by direct code read. **Treat `PRODUCT_STATUS.md`'s claim as wrong, not just outdated** — this is exactly the kind of contradiction between docs that should never be resolved by picking whichever one sounds better.
- [ ] **No token revocation mechanism at all** — confirmed: no `iat`/`nbf`, no blocklist anywhere in `auth.py`. A removed/demoted member's existing JWT stays fully valid until natural expiry (60 min default).
- [x] **Tenant scoping** — a per-query convention, not framework-enforced (documented, unchanged); no cross-tenant leak found in any code path checked this session, but nothing structurally prevents a future query from omitting the filter.
- [ ] **API keys cannot authenticate a request** — CRUD-only, confirmed (see Section 1).
- [ ] **Custom/granular RBAC** — 5 fixed roles, no per-permission adjustment, no custom roles. Not built, not claimed to be.

---

## 5. Security and credentials

- [x] **`custom_sql` quality-rule SQL-injection-shaped hole is fixed and still holds** — re-verified by direct code read 2026-08-18: routed through `SqlRunner`'s safety layer (`rule_engine.py:269-274`), not the raw connector. Originally a live Critical-severity finding, fixed same-day 2026-08-04.
- [ ] **`connection_config` (source credentials) stored as plaintext JSON, no encryption at rest** — Finding 39, re-confirmed still true.
- [ ] **No general API rate limiting** — Finding 38, re-confirmed. Password login and the chat endpoint are both unthrottled beyond a monthly credit quota.
- [ ] **Credential rotation not done** — `changeme` Postgres password, 9-char JWT secret, still both true (dev-only, but genuinely still open).
- [x] **SQL sandbox (`SqlRunner`) and Python sandbox (`PythonRunner`)** are both real and deliberately documented as "sufficient for LLM-validated code, not untrusted input" — correctly scoped, not overclaimed, per the code's own docstring.
- **[?] SQL sandbox is a keyword blocklist, not a real parser** (`PRODUCT_AUDIT.md` finding 19, not independently re-verified this session but architecturally unchanged — no test exists that would have caught a regression either way) — doesn't stop `pg_sleep()`-based timing abuse or an expensive `EXPLAIN ANALYZE` that actually executes.
- [x] **CORS** — `allow_origins` reads from config (defaults to `localhost:3000`), `allow_credentials=True`, methods/headers wide open. Fine for dev; needs a real production origin list before any real deploy (not urgent, nothing is deployed).
- [x] **No general HTTP security-header hardening checked this session** (HSTS, CSP, etc.) — out of scope for this pass given no production deployment exists yet; flagged as something to revisit before real launch, not claimed either way here.

---

## 6. Testing and CI

- [x] **Backend: 399/399 passing, 0 failures** (398 default + 1 live_llm), confirmed live this session.
- [ ] **No CI pipeline exists** — `.github/workflows/` absent. Every "verified" claim in this project's history happened because a person remembered to run something manually — the structural root cause behind nearly every "shipped but silently broken" finding in `PRODUCT_AUDIT.md` and this document.
- [ ] **Zero frontend automated tests** — confirmed, no framework installed.
- [ ] **No dedicated test for `sql_runner.py`/`python_runner.py`'s safety-critical sandboxing logic** — the two modules doing the most safety-critical work in the backend have no test directly exercising their blocklist/AST-check against a malicious or borderline payload. Re-checked this session: still true (`test_custom_sql_rule_safety.py` tests the quality-rule integration point, not the runner's own boundary conditions).
- [ ] **No security-focused testing anywhere** — no sandbox-escape attempt, no blocklist-bypass attempt, no rate-limit-abuse scenario tested (consistent with rate limiting not existing to test).

---

## 7. Infrastructure and deployment

- [ ] **17 commits unpushed to `origin/master`** — single point of failure, re-confirmed worse than documented.
- [ ] **No production deployment exists** — domain `wunomo.in` purchased, not configured (per `WUNOMO_MASTER_CONTEXT.md`, not re-verified live this session — no DNS/hosting check performed).
- [ ] **Nightly backups not set up** (per `WUNOMO_MASTER_CONTEXT.md`, not independently re-verified this session).
- [x] **Billing free-upgrade hole already closed** (per `WUNOMO_MASTER_CONTEXT.md`, `POST /change-plan` confirmed a real `501` stub this session — self-serve plan changes are correctly disabled, not silently broken).
- [?] **Cloudflare R2 file-storage migration "confirmed not launch-blocking"** — carried forward from `WUNOMO_MASTER_CONTEXT.md`, not independently re-verified.
- [x] **Two `docker-compose.yml` files with drifted container/volume names** — still both present, documented gotcha, unchanged.

---

## 8. Documentation

- [x] **`docs/context/` split (CLAUDE.md + 6 satellite files) is genuinely load-bearing** — cross-checking it against code this session surfaced real, accurate, specific history (the enum-case cluster, the migration-drift saga, the argument-resolution arc) that would otherwise only exist in unrecoverable chat history.
- **[?] Multiple internal inconsistencies found this session, not previously reconciled:**
  - `docs/PRODUCT_AUDIT.md` itself contradicts its own Section 3 (ranked list, item 3, no strikethrough) against its own Section 7 (item 2, struck through as fixed) for the `custom_sql` finding — the ranked list was never updated after the same-day fix landed.
  - `docs/PRODUCT_STATUS.md` vs. `docs/context/GOTCHAS.md` directly contradict each other on JWT revocation behavior (Section 4 above) — never reconciled.
  - `STATUS_TABLE.md`'s Billing (Phase 17) row vs. the currently shipped `/billing` page — never reconciled (Finding 42), independently caught twice (once in `PRODUCT_AUDIT.md` 2026-08-04, once again by this session's frontend subagent, meaning the first catch never got fixed).
  - `docs/context/STATUS_TABLE.md`'s "Not yet built" section states "Current suite (9 tests)" — badly stale (real count: 399); the section header itself may not have been touched in a very long time even as other parts of the same file were kept current.
- [ ] **`SELF_TEST_GUIDE.md` has real gaps** — Findings 43 (stale §1.3 login-page claim) and 44 (`/cicd` and `/` entirely absent from the walkthrough).
- [x] **`WALKTHROUGH_FINDINGS_2026-08.md` is now the single canonical bug-index** — 44 items as of this audit (32 pre-existing + 12 new, items 33–44, added alongside this report), a mix of user-reported UX findings and code-audit findings from three separate sessions now consolidated into one numbered list rather than scattered across `PRODUCT_AUDIT.md`'s own separate ranking.

---

## Phase 3a — BLOCKS A PAID CUSTOMER, ordered by severity

1. **No encryption at rest for connected-source credentials** (Finding 39). A real customer's database password, API token, or Google service-account private key sits in plaintext JSON in this app's own database. A breach of this app's DB is a breach of every connected customer system simultaneously. Highest severity because it's a data-loss/compliance event waiting to happen, not a functional bug.
2. **No rate limiting on password login or the chat endpoint** (Finding 38). Credential stuffing against the highest-traffic login path is currently unthrottled by anything but bcrypt's own cost factor. The chat endpoint's only cost control is a monthly quota, not a per-minute abuse guard.
3. **`BusinessRules.create_rule()` cannot create any business rule** (Finding 37). An entire advertised capability (8 rule types) is uncreatable through its own API — a customer configuring this feature hits a wall on the very first attempt, with no workaround visible from the outside.
4. **`contract_service.validate_contract()` always reports every column missing against a real profiled source** (Finding 34). Data Contracts is a governance-sell feature; a customer using it exactly as intended gets a false, alarming "everything is broken" result every single time.
5. **CI/CD's schema-drift check has silently no-op'd since it was built, and the auto-rollback safety net has never had a live trigger** (Findings 35, 40). A customer relying on CI/CD's stated safety guarantees ("schema drift blocks risky deploys," "2 failed runs auto-rolls-back") is trusting two mechanisms that have never actually functioned.
6. **Quality's `freshness` rule type silently always passes** (Finding 36). A customer configuring a freshness SLA check believes they have monitoring where none exists — the worst kind of gap, because it looks identical to success.
7. **17 commits, and everything built in the last week, exist on one machine only.** Not customer-facing directly, but a single hardware failure would set the whole project back to 2026-08-01's state.
8. **`run_quality_checks` cannot actually validate `sync_profile_quality` tasks end-to-end** (residual gap noted under Section 3) — the task shape structurally has no way to give this tool a real `pipeline_id`, so this specific automated workflow can complete "successfully" while doing nothing meaningful at its final step.
9. **JWT revocation gap** — a removed or demoted team member keeps full access for up to 60 minutes after removal. Known, documented, but worth restating as customer-facing: "I removed someone" does not mean "they're out," for up to an hour.
10. **Quality rule-creation UI can't configure 5 of its 8 rule types** (`PRODUCT_AUDIT.md`, not independently re-verified this session but architecturally unchanged) — a real, immediate usability dead end.

## Phase 3b — NEVER EXERCISED, ranked by blast radius if wrong

1. **`detect_schema_drift`** (AXIOM tool) — reachable by every role including Viewer, no approval gate, and its real implementation writes to the database. Zero test, zero cited live run. Highest blast radius of anything in this list because it's simultaneously unverified *and* under-gated.
2. **CI/CD's 6 never-exercised endpoints** (`commits/{id}` detail, `deployments/{id}` detail, `record-run`, `deployments/{id}/health`, `incidents` list) — a segment that's supposed to be an automated safety net, with the least real exercise of any segment in the backend.
3. **Governance's 5 never-exercised endpoints** (`lineage/{asset_name}`, `lineage/node`, `lineage/edge`, `contracts` list, `contracts/{id}` detail) — a compliance-relevant feature area for exactly the vertical (fintech) this product's own market research names as highest-willingness-to-pay.
4. **Analytics' 4 never-exercised endpoints** (`/pipelines`, `/kpis` GET+POST, `/usage`) — worst proportional ratio in the backend (63%); `/kpis` in particular is a write endpoint (`POST /kpis`) that has genuinely never been called by anything.
5. **`backfill_pipeline`, `ingest_file`, `preview_source_data`** (AXIOM tools) — mutating or near-mutating tools with zero test and zero individually-named live run, sitting in files whose siblings were all individually punch-listed and fixed — these three simply never got their own pass.
6. **Sources' 4 never-exercised endpoints** (`GET/{id}`, `PUT/{id}`, `preview`, `drift`) — `POST /{id}/drift` in particular backs a feature (`detect_schema_drift`) already flagged above as a live mutation at the lowest risk tier.
7. **`GET /api/v1/runs/{pipeline_id}`** — likely dead code, but "likely dead" is not "confirmed dead"; worth a deliberate check before deleting, not assuming.
8. **`POST /approvals/{id}/reject`** — the one half of the core approval mechanism never automated-tested and never individually named as manually clicked either.

## Phase 3c — CLAIMED BUT UNVERIFIED

1. **`docs/PRODUCT_STATUS.md`'s JWT-revocation claim, directly contradicted by later live evidence in `GOTCHAS.md`** — the single clearest example found this session of a doc asserting something that turned out to be false once someone actually checked. See Section 4.
2. **`/billing`'s only citation describes a UI that no longer exists in the code** (Finding 42) — flagged once already in `PRODUCT_AUDIT.md` 2026-08-04, still unreconciled 14 days later.
3. **`STATUS_TABLE.md:34`'s "all 5 governance tools live-verified" claim** — the supporting narrative only individually names 4; `get_lineage` is bundled in without its own evidence.
4. **`get_lineage`, `ingest_file`, `preview_source_data`, `detect_schema_drift`, `backfill_pipeline`** — all sit in a codebase whose own `GOTCHAS.md` explicitly warns "treat any tool you haven't personally live-verified as unverified, regardless of what the Status Table says elsewhere." That warning exists because of a documented historical pattern (the 22-site tool punch list) — these five are the same pattern's next instance, just not yet caught by a live call the way their siblings were.
5. **`STATUS_TABLE.md`'s "Not yet built" section's "current suite: 9 tests" line** — off by roughly 44x from the real, current count (399). A reminder that even the parts of this project's own documentation infrastructure built specifically to stay honest can go stale if a section isn't touched for long enough.
6. **`docs/PRODUCT_AUDIT.md`'s own internal contradiction on the `custom_sql` fix** — Section 3 (ranked list) still shows it as an open, unstruck finding; Section 7 shows it struck through as fixed the same day. Both can't be the current, intended state of that one document — re-verified independently this session that the fix genuinely holds, so Section 7 is correct and Section 3 simply never got updated to match.
7. **The `sync_profile_quality` task shape's own completion is trustworthy only for 3 of its 4 steps** — the shape reaches `COMPLETED` (live-proven, real), but its final step's "success" cannot currently mean what a reasonable reader would assume, per the residual gap noted in Section 3.

---

## Closing note

The backend is genuinely solid where it's been exercised — 399/399 tests, a clean production frontend build, a real and increasingly well-verified Tasks/argument-resolution subsystem that reached actual `COMPLETED` states against real data this week. The pattern that should worry a technical reviewer most is not any single bug in this document — it's that **the same specific findings, once discovered, tend to sit unfixed and unconsolidated across multiple documents for weeks**: the `custom_sql` fix that never got its own ranked-list entry updated, the Billing doc-drift caught once on 2026-08-04 and still uncorrected 14 days later, the JWT-revocation claim contradicted by a later document that nobody went back and reconciled with the earlier one. None of that is unusual for a fast-moving solo/small-team project — but it is exactly the shape of gap a due-diligence process exists to surface, and exactly why this audit's own standard (a claim is not evidence unless it names a specific test, commit, or dated live check) matters more here than in a codebase with less history of things looking done before they were.
