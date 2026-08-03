# AXIOM Product Audit — Brutally Honest Assessment

**Date:** 2026-08-04. **Method:** direct code reading (backend + frontend), not CLAUDE.md's self-reports — every claim below is grounded in a specific file/function I (or a research pass I directed and then spot-checked) actually read. Where this document disagrees with CLAUDE.md's narrative, that's flagged explicitly, because the disagreement itself is a finding.

This is not a summary of what was built. It's an assessment of where it falls short.

---

## 0. Executive summary

AXIOM's backend is a genuinely substantial, mostly-correct DataOps CRUD/orchestration API with real multi-tenant auth, real RBAC, real Celery scheduling, and a real (if narrow) LangGraph agent on top of it. The frontend is a complete, mostly-honest 19-screen app with no fabricated data on any *shipped* screen. Both of those statements are true and worth stating plainly before the rest of this document, which is not going to be kind.

The single biggest gap is not a bug — it's a mismatch between the product's stated ambition and its actual architecture. **AXIOM was pitched as an AI employee that takes a task and goes and does it. What's actually built is a chat interface that mostly reports, occasionally mutates its own metadata layer, and — in the one place specifically designed to let it take real, higher-risk action under human oversight (the approval workflow) — silently does nothing at all.** Section 1 covers this in full; read it first.

Beyond that: this codebase has a real, repeating pattern of shipping code that was never exercised against the thing it calls into (the 22-site tool-call punch list, the migration-drift discovery, and — new in this audit — `contract_service.py`'s unfixed twin of the same bug, `business_rules.py`'s unusable `create_rule()`, and `cicd_tasks.py`'s permanently-no-op schema check). None of these individually are shocking; the *pattern* — code that looks done, was never actually run, and sat undiscovered for months — is the thing a technical reviewer should take most seriously, because it means "verified" in this project's own history has not reliably meant "verified."

---

## 1. AXIOM's agency — why it mostly analyzes and reports rather than acting

### 1.1 The full action path, traced end to end

```
User message
  → POST /api/v1/chat/  (api/v1/chat.py)
  → run_agent()  (agent/dataops_agent.py)
  → LangGraph: inject_system → agent_node → role_denied_tool_calls (strip) → approval_gate_node
       ├─ not blocked → ToolNode (real tool executes) → loop back to agent_node (≤10 iterations)
       └─ blocked     → END, "Approval Required" message, pending_approvals returned
  → chat.py persists any pending_approvals as real ApprovalRequest rows
  → [if not blocked] real tool side effect already happened, response returned to user
  → [if blocked] user must separately visit /approvals and click Approve
       → PolicyEngine.approve() → execute_approved_action() → TOOL_REGISTRY dispatch
       → BROKEN (see 1.2) — nothing real happens for 10 of 11 registered actions,
         a silent no-op for the 11th
  → chat thread is NEVER updated with the outcome (see 1.3) — it stays frozen on
    "Needs approval" forever, regardless of what happens on the Approvals screen
```

Two things are true simultaneously, and the distinction matters: **direct tool execution (the non-approval path) works correctly** — this was proven repeatedly across this project's own history (the 22-site tool-call punch list, live multi-turn tool-calling verifications). The graph's ReAct loop can genuinely chain multiple real tool calls in one turn, up to `MAX_AGENT_ITERATIONS = 10` (`agent/dataops_agent.py:105`). **It is specifically the approval-gated path — the one path this architecture built to let AXIOM take higher-risk, higher-trust action — that is completely non-functional.** That's the worst possible place for this bug to live: it means AXIOM's *safest* action-taking mechanism, the one an operator is supposed to trust precisely because a human signed off, is the one that does nothing.

### 1.2 `execute_approved_action()` — confirmed broken, and worse than previously documented

`TOOL_REGISTRY` (`modules/governance/policy_engine.py:23-41`) has **11 entries**, not the 8 CLAUDE.md's Known-broken table currently states — I counted directly from the dict. `execute_approved_action()` (line 319) resolves each via:

```python
module = importlib.import_module(module_path)
fn = getattr(module, fn_name, None)   # MODULE-LEVEL lookup
```

Every real target (`DAGManager.trigger_run`, `DAGManager.backfill`, `DAGManager.pause`, `QualityRuleEngine.run_checks`, `BusinessRules.update_rule`, `IncidentManager.resolve_incident`, `IncidentManager.triage_incident`, `SchemaProfiler.profile`, `ConnectorManager.sync`, `ReportGenerator.generate_status_report`) is an **instance method**, not a module-level function. `getattr()` returns `None` for all ten. The eleventh, `update_contract`, is mapped to `policy_engine._noop()` — a real module-level function that exists specifically as a stub, returning `{"status": "noop", "kwargs": kwargs}`.

The consequence for the eleventh entry is worse than the other ten, not better: because `_noop()`'s return dict has no `"error"` key, `PolicyEngine.approve()`'s own logic (`final_status = EXECUTED if "error" not in execution_result else FAILED`, line 226) marks that approval **`EXECUTED`** — a clean, successful-looking status, for an action that did *nothing at all*. The other ten at least surface a visible `FAILED` status with `"Function '<name>' not found in module '<path>'"` as the error. **One out of eleven approval types doesn't just fail to act — it actively reports success while acting on nothing.**

No test anywhere in the suite asserts that `execute_approved_action()` successfully executes a real registered action. That absence is itself confirmation: this has never worked, and nothing was verifying it.

### 1.3 Approval outcomes never return to the chat thread — confirmed

`GET /chat/sessions/{id}/history` (`api/v1/chat.py:172-187`) reads `ChatMessage.tool_calls` exactly as it was written at turn time and returns it verbatim — there is no reference anywhere in that function to `ApprovalRequest`. A tool call tagged `"status": "blocked_pending_approval"` at write time stays that way in the chat transcript forever, regardless of what later happens on the Approvals screen (approved, rejected, or — per 1.2 — approved-but-silently-nonfunctional). A user re-opening a conversation from days ago sees a permanently frozen "Needs approval," with no way to tell from the chat itself whether anything ever happened. This was proposed as a cheap fix (a join against `ApprovalRequest.status` at read time, `FRONTEND_BUILD_PLAN.md` P1 item #13) and never built. Confirmed still true by direct code read.

### 1.4 Of the 39 tools, how many actually mutate state?

`services/rbac.py`'s `TOOL_CAPABILITIES` map (the authoritative classification both the REST and agent layers already use) gives a precise split. Counting directly from `agent/tools/*.py` (39 tools total, not 38 — CLAUDE.md is off by one):

- **16 tools map to `"view"`** (pure read/report, granted to every role including Viewer): `list_data_sources`, `preview_source_data`, `detect_schema_drift`, `get_quality_report`, `list_business_rules`, `get_pipeline_run_history`, `list_open_incidents`, `get_system_health`, `get_lineage`, `get_audit_trail`, `request_approval`, `generate_status_report`, `generate_incident_report`, `export_dataset`, `get_kpi_summary`, `get_cicd_status`.
- **23 tools map to an operational capability** (`sources.*`, `pipelines.*`, `quality.manage`, `transforms.execute`, `incidents.resolve`, `contracts.*`) — on paper, "mutating."

But that 23 overstates AXIOM's real reach into a tenant's actual data, for two structural reasons:
- **2 of the 23 are outright stubs**: `standardize_dataset` and — despite being tagged `"view"` above, worth restating here — `export_dataset` both unconditionally return `{"error": "not implemented... do not tell the user this succeeded"}`.
- **2 more (`execute_sql_transform`, `run_python_transform`) can never mutate the tenant's actual source data, by design.** `SqlRunner` only permits `SELECT`/`WITH`/`EXPLAIN` (a first-token check plus a keyword blocklist); `PythonRunner` has no write-back path to the source at all — it can only write to AXIOM's own `TransformRun` log. These two tools *look* like mutation tools and are gated as `transforms.execute`, but they are read-only against the actual business data every time.

So the real count is: **16 pure-read + 2 stubs + 2 sandbox-constrained-to-read = 20 tools that never change a tenant's real data**, versus **19 tools that do** — and every one of those 19 acts exclusively on AXIOM's *own* orchestration/metadata layer (create/trigger/pause/schedule a pipeline, register/sync/profile a source, create/run a quality rule, triage/resolve an incident, create a contract, send an alert). **There is no tool anywhere in this system that can INSERT/UPDATE/DELETE a row in a tenant's actual connected database.** That's not an oversight — `SqlRunner`'s restriction is a deliberate safety boundary — but it means the tool set is not "weighted toward analysis by accident." It is weighted toward *orchestration-of-AXIOM's-own-configuration* by explicit design, and structurally incapable of the thing "AXIOM fixes your data" would actually require. Those are two different products, and the current one is closer to "an operator for a fixed set of DataOps primitives" than "an agent that can go fix what's broken."

### 1.5 Can it chain multi-step work? Does it verify its own results?

**Yes to chaining, within a turn.** The graph's `agent → approval_gate → tools → agent` loop genuinely supports multiple real tool calls per turn (proven live in this project's own history — e.g., a single turn that registered two sources then re-listed them). This is real ReAct-style tool chaining, not a single-shot illusion.

**No to verification, structurally.** Every tool that dispatches asynchronous work returns immediately with a pending status — confirmed by reading `DAGManager.trigger_run()` (`modules/orchestration/dag_manager.py:194-239`), which creates a `PENDING` `PipelineRun`, calls `execute_pipeline_run.delay(...)` (fire-and-forget into Celery), and returns `{"status": RunStatus.PENDING, "dispatch": "queued"}` in the same function call — there is no polling, no wait, no "block until this actually finishes" anywhere in the tool or the graph. Nothing in `personality.py`'s system prompts instructs the model to check back before reporting success, and nothing in the graph structure forces a follow-up read after a mutating call. **AXIOM will report "I've triggered the pipeline" in the same breath a human would, with zero information about whether it actually succeeded** — that information only exists if the user (or the LLM, entirely at its own unprompted discretion) asks a follow-up question in a later turn.

### 1.6 What does it do when a tool fails?

Two genuinely different failure classes exist here, and only one is understood:

- **LLM-API-level failures** (a malformed tool-call request rejected by the provider, both providers' fallback exhausted) — **confirmed broken**, documented in CLAUDE.md's Known-broken table: this crashes `POST /chat/` with an unhandled 500, no graceful degradation, no `ChatMessage` persisted.
- **Tool-function-level failures** (an exception raised inside the Python tool itself, e.g. a bad argument reaching a real `KeyError`) — LangGraph's stock `ToolNode` (used here with no override, `agent/dataops_agent.py:234`) catches these by default and returns the error as `ToolMessage` content, which *should* let the LLM see the failure and adapt on the next loop iteration. **This is a framework default, not a verified behavior in this codebase** — I found zero tests anywhere that exercise a real tool-level exception and assert the agent adapts. Treat "AXIOM can recover from a tool bug" as a plausible-but-unproven assumption, not a demonstrated capability.

There is no retry-with-backoff, no "try a different approach" heuristic, and no cap on *how many times* the same failing call can be retried within the 10-iteration budget beyond that budget itself.

### 1.7 What would it take to complete a real task end-to-end without a click? Sized gap list.

| # | Gap | Size | Why |
|---|---|---|---|
| 1 | Fix `execute_approved_action()` dispatch | **Medium** | Needs `TOOL_REGISTRY` to carry enough to instantiate the owning class with `tenant_id` (and `user_id`/`session_id` where required) before calling the bound method — a real architecture change to the approval-execution mechanism, which this project's own Workflow Rule 4 requires proposing before coding. Needs a test per registered action proving it actually executes, not just resolves. |
| 2 | Close the approval-return-to-chat gap | **Small** | A join against `ApprovalRequest.status` at `GET /chat/sessions/{id}/history` read time — already scoped as a cheap fix in `FRONTEND_BUILD_PLAN.md` P1 #13, never built. |
| 3 | Fix `RISK_ACTIONS`' phantom tool names | **Small** | `personality.py`'s `"high"` tier lists 4 tool names (`delete_records`, `drop_table`, `modify_schema`, `revoke_access`) that don't exist anywhere in `ALL_TOOLS`. Real destructive-shaped actions never actually reach "high" risk today. This is foundational — items 1 and 2 are pointless to fix if the risk gate they feed almost never fires for anything real. |
| 4 | Add a "verify after acting" step | **Medium** | Either a structural graph node that re-checks status after a mutating call before the turn ends, or (weaker, not recommended alone) prompting. A structural node is the only way to make this reliable rather than aspirational. |
| 5 | Wire the existing `notify_*` presets into real trigger points | **Small-Medium** | The code (`NotificationService.notify_incident/notify_stale_sources/notify_pipeline_failure`) already exists and is tested-adjacent but is never called from `_check_freshness()`, `_execute_run()`'s failure branch, or incident creation. An agent that only ever *reports when asked* isn't proactive — this is a cheap, real step toward "tells you something's wrong" instead of "waits to be asked." |
| 6 | A background/async task-execution mode for AXIOM's own reasoning loop | **Large, architectural** | Every turn today is bounded by one synchronous `POST /chat/` request/response cycle. There is no way to hand AXIOM a goal and let it work for minutes while reporting progress back later — the "give it a task like Claude Code and check back" vision requires a queued goal object, a Celery-driven agent loop, and a UI surface (a task/job view, not just a chat thread) distinct from what exists today. |
| 7 | Real write-capable data tools | **Large — a deliberate product/safety decision, not just an engineering task** | Nothing today can `INSERT`/`UPDATE`/`DELETE` a tenant's actual connected data. If "AXIOM fixes your data" is the real ambition, this is the actual gap, and closing it means designing real approval-gating, audit trail, and blast-radius limits for genuine data mutation — not a small addition to the existing sandbox. |

**Recommended build order:** 3 → 1 → 2 → 5 → 4 → 6/7 (6 and 7 are independent, larger bets — sequence whichever matches the more urgent version of "agency" you want first: *autonomy over longer tasks* (6) vs. *real data-changing power* (7)). Items 3, 1, and 2 together are what make the *existing* approval architecture actually true — that's the cheapest, highest-leverage fix available, and it should land before either of the two big bets, because right now the thing a demo would show off (approve an action, watch it happen) is the one thing in this whole system guaranteed not to work.

---

## 2. Feature-by-feature status

Status key: **Fully working** (real, wired, verified by reading the actual implementation) / **Partially working** (specifics given) / **Broken** / **Stubbed** / **Missing**.

| Area | Status | Specifics |
|---|---|---|
| Auth (password / Google OAuth / email-code) | **Fully working**, with one real gap | All 3 methods genuinely implemented, not stubbed. Password login has **zero rate limiting or lockout** — no Redis counter, no per-IP throttle, nothing but bcrypt's own cost factor — in sharp contrast to email-code's 4-layer rate limiter. This asymmetry means the highest-traffic login method is the least protected. |
| Sources / Ingestion | **Fully working** for CRUD; connection-config UX is a real gap | All 6 connectors real. Credentials entered as raw JSON in a textarea with a literal `"password": "***"` placeholder — no masking, no per-field form, no test-connection button. |
| Pipelines / Orchestration | **Partially working** | Real CRUD, real triggering, real Celery-based scheduling (`check_scheduled_pipelines()`, confirmed live and correct). Execution itself is a fixed 2-step linear sequence (sync → quality check), not a real DAG — no dependency graph exists at either layer, so the frontend's DAG-shaped nav icon points at a flat table. `Scheduler` (the originally-designed dynamic class) is confirmed dead code — never called, and architecturally could not have worked across the backend/celery_beat process boundary even if it were. |
| Quality | **Partially working — see specifics, this is worse than previously documented** | Of 8 declared rule types: `not_null`/`unique`/`accepted_values`/`range`/`regex`/`row_count` work end to end. **`freshness` is declared but never implemented — it silently always passes**, indistinguishable from a real passing check (new finding, not in CLAUDE.md). **`custom_sql` bypasses `SqlRunner` entirely and executes arbitrary, unsandboxed SQL** against the tenant's real connected database — reachable via REST and chat (new finding, a real security hole). `test_runner.py` (`QualityTestRunner`) is dead code with a broken import and 100%-hardcoded-pass stubs. |
| Business rules | **Broken for creation** | All 8 rule-check implementations (`_check_reconciliation`, etc.) are real and competently written. `BusinessRules.create_rule()` validates against the wrong type list (the base 8 quality types, not the 8 business-rule types) — **no business rule of any kind can be created through its intended API today.** The test suite works around this by inserting rows directly, bypassing the broken method. |
| Incidents / Observability | **Fully working** — one of the more solid modules | Real freshness/health/anomaly-detection logic, real LLM-backed triage with structured parsing. One cosmetic bug: `triage_incident()` hardcodes the model name in its result regardless of which provider actually served the call. |
| Governance — Lineage / Audit | **Fully working** | Real idempotent lineage graph with self-healing sync; real audit trail. |
| Governance — Contracts | **Partially working, one live bug** | `create_contract()` is solid. `validate_contract()` reads `schema_snapshot` as a flat `{"columns": [...]}` shape, but `SchemaProfiler` always nests it per table — **every validation against a genuinely profiled source will incorrectly report every expected column as missing.** This is the identical bug class already found and fixed in `TransformGenerator._resolve_schema()`, left unfixed here, and untested (the one validation test only exercises the unprofiled-source branch). |
| Governance — Approvals execution | **Broken** | See Section 1 in full. |
| CI/CD | **Partially working, with two previously-undocumented dead paths** | Webhook verification, commit persistence, and deployment activation are solid. **`run_schema_check()` permanently no-ops** — it imports a `models.schema_snapshot.SchemaSnapshot` that does not exist anywhere in the repo, caught by its own `except ImportError`, silently excluding schema-drift from every risk score ever computed. **`run_sql_static_analysis()` scans filenames + commit message text, never actual file/diff content** — a real `DROP TABLE` in a changed file sails through if the commit message doesn't mention it. **The post-deploy auto-rollback monitor has no live trigger** — the counters its decision depends on are only incremented by an endpoint (`POST /deployments/{id}/record-run`) that the real pipeline executor never calls. |
| Approvals (REST/UI) | **Partially working** | Request/list/reject lifecycle and the merged-queue endpoint are correct and well-tested. Execution is broken (Section 1). |
| Team / Billing / Settings / API keys | **Fully working — the best-built cluster in the codebase** | Invites, role management, quota enforcement, and API-key CRUD are all real, tenant-scoped, and well-tested. `POST /change-plan` is already disabled (confirmed `501` in the live code) — **CLAUDE.md's own banner describing this as a not-yet-executed next step is stale; the code is already ahead of the doc.** |
| Analytics / Reporting (backend) | **Partially working** | Real aggregate endpoints and a real 4-mode report generator. `NotificationService`'s 3 convenience presets (`notify_incident`, `notify_stale_sources`, `notify_pipeline_failure`) are dead code — grepped, called from nowhere — meaning the freshness checker creates real incidents every 15 minutes and **never notifies anyone automatically**; the only live caller of notifications anywhere is the chat tool `send_alert`, triggered only when explicitly asked. |
| Transforms / Catalog | **Fully working, well-engineered** | `PythonRunner`'s AST-sandbox and `SqlRunner`'s safety layer are both genuinely careful (with caveats, see Section 4). `TransformGenerator`'s schema-grounding fix is real and correctly applied (unlike its unfixed twin in `contract_service.py`). |
| Dashboard (frontend) | **Fully working**, one real inconsistency | All KPIs/charts/cards wired to real endpoints. Uses the *policy_engine-only* approvals endpoint while the dedicated Approvals screen uses the *merged* one — a CI/CD deployment stuck pending approval never appears in the Dashboard's count. |
| Chat / AXIOM UI | **Fully working**, the most solid screen | Real everything, including a genuinely careful stale-response race guard. Renders assistant text via `dangerouslySetInnerHTML` through a hand-rolled regex "sanitizer," not a real sanitization library — fragile, not currently exploited. |
| Sources / Catalog / Pipelines / Transforms / Incidents / CI/CD / Team / Settings / Approvals (frontend) | **Fully working** | All wired to real endpoints, no fabricated data found in any of these screens. |
| Quality (frontend) | **Partially working — a real, concrete gap** | The rule-creation form has one generic optional "Column" field regardless of rule type — no min/max for `range`, no value-list builder for `accepted_values`, no pattern field for `regex`, no SQL box for `custom_sql`. **5 of 8 advertised rule types are effectively unusable from this UI as built.** |
| Governance — Lineage tab (frontend) | **Partially working, overclaims its label** | Two flat HTML tables (nodes, edges), no visual graph, no zoom/pan, no column-level lineage. Satisfies the word "lineage," not the expectation the word sets. |
| Automations, Analytics (nav), Audit (frontend) | **Stubbed** | All three are literal `<StubPage>` placeholders. Audit is the worst of the three: a fully real, working audit trail already exists — inside Governance's third tab — while the dedicated `/audit` route the sidebar links to shows nothing. A real information-architecture defect, not just an unfinished feature. |
| Billing (frontend) | **Fully working, but confirms doc drift** | The plan-picker UI CLAUDE.md's Phase 17 entry describes has been removed; the current screen is read-only-plan + usage bars + honest "handled manually" copy. Correct and current; the *documentation* about it is what's behind. |
| AI Employees, Landing, Auth/Onboarding (frontend) | **Fully working**, no overclaiming found | Honest "Coming Soon" states, no fabricated numbers/testimonials, real screenshots. No Privacy Policy/ToS link or acceptance checkbox anywhere (domain-gated, already tracked). |

---

## 3. Known bugs, gaps, and shortcuts — ranked by how much they hurt a real user

1. **`execute_approved_action()` dispatch broken for all 11 registered actions** (Section 1.2) — the core "approve → it happens" promise is entirely false today, and one variant of it actively lies about success.
2. **Approval outcomes never reflected in chat** (Section 1.3) — compounds #1 into a permanently misleading conversation transcript.
3. **`custom_sql` quality rule executes arbitrary, unsandboxed SQL** against a tenant's real connected database, reachable from both the REST API and the chat agent — a genuine, live security hole, not hypothetical.
4. **No CI pipeline of any kind** — zero automated test execution on push/PR, for either backend (270+ tests) or frontend (zero tests exist to run). Every "verified" claim in this project's history happened because a person remembered to run something manually. This is the structural root cause of nearly every "shipped but silently broken" finding in this document.
5. **Zero frontend automated tests** — confirmed via `package.json` and a repo-wide search: no test framework installed, no test files exist. Every historical "live-verified via Playwright" claim describes a one-off script, run once, never committed, never re-runnable.
6. **CI/CD's schema-drift check has always silently no-op'd** — imports a model that doesn't exist, caught by its own exception handler, excluded from every risk score computed to date.
7. **CI/CD's auto-rollback safety net has no live trigger** — the real pipeline executor never calls the endpoint that feeds the rollback decision.
8. **`contract_service.validate_contract()`'s flat-schema bug** — every contract validation against a genuinely profiled source will wrongly report all columns missing.
9. **`BusinessRules.create_rule()` cannot create any of its 8 supported rule types** — an entire advertised feature is uncreatable through its own intended path.
10. **Quality's `freshness` rule type silently always passes** — a deceptive stub with zero visible indication it isn't real.
11. **No encryption at rest for connection credentials** — `DataSource.connection_config` stores real DB passwords, API tokens, and (for Google Sheets) service-account private keys as plaintext JSON.
12. **No rate limiting on password login** — the highest-traffic auth path is also the least protected against brute force/credential stuffing.
13. **No rate limiting on the chat endpoint** beyond a monthly credit quota — no per-minute abuse throttle on the single most expensive real per-request cost driver in the app.
14. **Notification presets never fire automatically** — real incidents/failures are created silently; nothing proactively tells anyone unless AXIOM is explicitly asked to send an alert mid-conversation.
15. **Dashboard vs. Approvals screen read from different approval queues** — currently correct in each place it's used, but a real landmine for the next person who touches either without noticing the split.
16. **Quality rule-creation UI can't configure 5 of its 8 rule types** — a real, immediate usability dead end for most rule types.
17. **Audit Logs nav item is a stub while a working audit log exists elsewhere** — a genuine information-architecture defect.
18. **Command Palette visually implies keyboard navigation ("↵" hint) it doesn't have** — zero arrow-key/Enter handling exists anywhere in the codebase.
19. **SQL sandbox is a keyword blocklist, not a real parser** — closes the obvious DDL/DML vectors but doesn't stop `pg_sleep()`-based timing abuse, `dblink`/`pg_read_file`-style functions, or an expensive `EXPLAIN ANALYZE` (which actually executes).
20. **Notifications panel is dead code containing fabricated placeholder data** — currently unreachable (no bell wired up), but a live landmine if anyone re-adds the entry point without noticing.
21. **Sidebar's "Production" workspace selector is decorative and its own toast is now stale** — points at "coming in Phase 15," a phase that has since shipped without this feature.
22. **`RISK_ACTIONS`' high-risk tier references phantom tool names** — real destructive-shaped actions essentially never reach "high" risk in practice (see Section 1.7 item 3).
23. **Pervasive lack of keyboard operability** — clickable `<div>`s with no `role`/`tabIndex`/`onKeyDown` across at least 5 components; modals have no focus trap.
24. **No Privacy Policy / Terms of Service anywhere**, and no acceptance step on signup (already tracked, domain-gated, restated here for completeness of the ranked list).
25. **CLAUDE.md itself has drifted from the shipped code** on at least one substantive point (Billing's removed plan-picker) — a documentation-integrity issue relevant to any reviewer who was told to trust that file.

---

## 4. Where the product is weakest vs. what a data engineer would expect

- **No real pipeline dependency graph**, at either the backend or frontend layer. Airflow-class expectations (DAG view, per-node status, click-through logs) don't apply here because there's no dependency concept to visualize — pipelines are a fixed 2-step linear sequence.
- **Lineage is table-level only, non-visual, and shallow.** No column-level lineage, no interactive graph, no blast-radius/impact analysis before a schema change — the single largest gap between what "Governance → Lineage" implies and what it delivers, relative to Monte Carlo/Atlan-class tools.
- **Alert routing is 4 checkboxes.** No per-pipeline/per-severity routing, no PagerDuty/Opsgenie/Teams integration, no dedup windows or escalation policies.
- **No schema diff/version history anywhere** — `last_profiled_at` exists, but there's no way to see what changed between two profiling runs.
- **No cost/usage attribution below the tenant level** — no per-pipeline or per-source AI-credit or run-cost visibility, a real gap for a tool whose own LLM calls are a genuine cost driver.
- **No multi-environment concept** — the "Production" label in the sidebar is a hardcoded decoration with no dev/staging distinction anywhere in the data model.
- **Audit log has no filtering, no pagination control, no export** — a real gap for any regulated-industry buyer evaluating this on governance/compliance grounds.
- **No custom/granular RBAC** — 5 fixed roles with fixed capability sets; no way to adjust an individual permission or define a custom role.
- **No enterprise SSO** — Google OAuth is consumer-style "Continue with Google"; nothing for an IT admin to configure org-wide SAML/OIDC.
- **No bulk operations anywhere** — every action is one row at a time, across every screen.
- **Connection-credential entry is worse than any comparable connector product** — a raw JSON textarea with an unmasked password placeholder, no test-connection step, versus Fivetran/Airbyte's structured, masked per-field forms.
- **Code editors are plain textareas** — no syntax highlighting, linting, or autocomplete in either the SQL or Python transform editors, a visible step down from dbt Cloud/Hex/Databricks.

---

## 5. Built fast, should be rebuilt properly

- **`modules/orchestration/scheduler.py`'s `Scheduler` class.** A correct, tested implementation of an architecture that could never have worked (mutates a dict that isn't shared across the backend/celery_beat process boundary). It sits next to the real mechanism (`check_scheduled_pipelines()`), confusing rather than informing. Delete it; don't keep it "for its own test coverage."
- **`PolicyEngine.TOOL_REGISTRY`'s dispatch mechanism.** A `getattr(module, fn_name)` lookup against a registry of instance methods was never going to work — this needs the architectural fix described in Section 1.7, not a patch.
- **`cicd_tasks.py`'s `run_sql_static_analysis()`.** Scanning filenames and commit messages for keywords, rather than actual changed content, doesn't do what its name claims. Either read real diff content or rename it to something honest about its limits.
- **The Quality rule-creation form.** A single generic "Column" field for 8 structurally different rule types was always going to be incomplete; it needs per-type conditional fields, not a bolt-on later.
- **`contract_service.py`'s schema reading.** The exact fix already exists, proven correct, in `TransformGenerator._resolve_schema()` — this isn't a design problem, it's an un-applied fix.
- **The transform SQL/Python editors.** Plain textareas were a reasonable v1 shortcut; for a screen whose entire purpose is writing code against real data, this reads as unfinished the moment a real data engineer opens it.
- **The two `docker-compose.yml` files with drifted container/volume names.** Already a known Gotcha; worth collapsing to one file rather than maintaining parity by hand indefinitely.

---

## 6. Test coverage gaps that actually matter

- **No CI pipeline exists at all** — the single highest-leverage fix available. Every gap in this document that "sat undiscovered" did so partly because nothing runs the existing 270+ backend tests automatically.
- **Zero frontend tests of any kind** — no framework installed, no files exist. Every "Playwright-verified" historical claim is unreproducible today.
- **`sql_runner.py`/`python_runner.py` have no dedicated test file** — the two modules doing the most safety-critical work in the backend (query/code sandboxing) have no test directly exercising their blocklist/AST-check logic against a malicious or borderline payload.
- **`rule_engine.py`'s per-rule-type evaluation logic has no dedicated test** — no test creates a real `not_null`/`range`/`custom_sql` rule and asserts the result against real data, which is exactly how the `freshness`-always-passes and `custom_sql`-unsandboxed findings went unnoticed.
- **No test exercises `execute_approved_action()` succeeding** for any real registered action — consistent with it never having worked.
- **No test exercises the CI/CD schema-check ImportError path, real-content SQL analysis, or a real pipeline run driving the rollback monitor's counters** — all three CI/CD gaps in this document are invisible to the existing suite.
- **No test exercises a genuine tool-level exception and the agent's recovery from it** — Section 1.6's retry/adapt behavior is entirely unverified.
- **No security-focused testing anywhere** — no test attempts a sandbox-escape payload, a SQL-injection-style bypass of the blocklist, or a rate-limit-abuse scenario.

---

## 7. What would embarrass this in a technical due-diligence review

1. **The approval workflow — the product's own trust mechanism — doesn't work**, and one of its eleven registered action types actively reports success while doing nothing. This is the single fact most likely to end a serious technical review early if discovered live rather than disclosed.
2. **A live, reachable, unsandboxed arbitrary-SQL-execution path** (`custom_sql` quality rules) exists in a product whose entire value proposition is trustworthy automation over a company's real data infrastructure.
3. **No CI pipeline**, for a codebase this size, with this much historical evidence that things silently broke and stayed broken for months.
4. **Plaintext credential storage** for every connected data source's password/token/service-account key.
5. **The project's own documentation has already drifted from the shipped code** on at least one substantive, checkable point — a bad sign for how much else in a 900-line CLAUDE.md might be stale in ways nobody's re-verified.
6. **A CI/CD "auto-rollback safety net" that has never once had live data to act on**, discovered only by tracing who calls what — this is exactly the kind of thing a due-diligence engineer traces first.
7. **Zero automated frontend testing**, for a product whose frontend is the majority of what a prospective buyer or investor would actually see and click through.

---

## Closing note

None of this changes the fact that the backend's tenant-scoped CRUD surface, RBAC, and Celery scheduling are real and mostly correct, or that the frontend has no fabricated data on any shipped screen. The gap between "a lot of real, working software" and "an AI employee that acts" is precisely and only Section 1 — and it's a closeable gap, not a fundamental one: the ReAct loop, the tool set, and the role/risk gating are all real infrastructure already in place. What's missing is finishing the one path (approval → execution) that was supposed to be the trust-building centerpiece, and then making a deliberate call about whether AXIOM should ever be allowed to write real data, versus staying a very capable orchestrator of its own metadata layer.
