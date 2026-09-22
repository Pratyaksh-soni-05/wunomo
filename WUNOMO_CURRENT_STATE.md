# AXIOM DataOps Agent — Current State Report

Factual, read-only audit of `dataops-agent/` as it exists in the repository on 2026-09-19. No code was changed to produce this report. Everything below was verified by direct reading of source files (plus, where noted, live execution against the running Docker stack and the real dev database).

---

## 1. TREE

Repo root (depth ≤ 4, excluding `node_modules/`, `.git/`, `__pycache__/`, `venv/`):

```
ai workforce/
├── CLAUDE.md
├── Vision.txt
├── WUNOMO_PROJECTS_PROPOSAL_v2.md
├── backups/
│   └── dataops_pre_incident_cleanup_20260820_113252.dump
├── dataops-agent/                       ← the one real application
│   ├── .env                             (real, gitignored, not committed)
│   ├── DESIGN_TOKENS.md
│   ├── Makefile
│   ├── README.md
│   ├── USER_MANUAL.md
│   ├── create_enums.sql
│   ├── docker-compose.yml
│   ├── backend/                         — 22,929 lines of app .py (excl. tests)
│   │   ├── agent/                       — 1,143 lines
│   │   │   └── tools/                   (8 tool modules)
│   │   ├── api/                         — 5,936 lines
│   │   │   └── v1/                      (23 router files)
│   │   ├── migrations/versions/         (26 Alembic migrations)
│   │   ├── models/                      — 1,047 lines
│   │   ├── modules/                     — 9,547 lines
│   │   │   ├── governance/
│   │   │   ├── ingestion/connectors/
│   │   │   ├── observability/
│   │   │   ├── orchestration/
│   │   │   ├── quality/
│   │   │   ├── reporting/
│   │   │   └── transformation/
│   │   ├── schemas/                     — 408 lines (10 files)
│   │   ├── scripts/                     — 80 lines
│   │   ├── services/                    — 4,223 lines (16 files)
│   │   ├── tests/                       — 16,626 lines, 85 files
│   │   └── main.py, config.py, database.py, diagnose.py, fix_analytics*.py, patch_analytics.py, seed_approval.py — 468 lines (root-level scripts, not under any module)
│   ├── frontend/                        — 14,068 lines of .ts/.tsx
│   │   ├── src/app/                     (login, signup, onboarding, invite, api/, and the `(app)/` route group: agents, ai-employees, analytics, approvals, audit, automations, billing, catalog, chat, cicd, dashboard, governance, home, incidents, pipelines, projects, quality, scheduled, settings, sources, tasks, team, transforms)
│   │   ├── src/components/              (agents, auth, brand, chat, dashboard, shared, shell, tasks, ui, workbench)
│   │   ├── src/lib/                     (single API client, `api.ts`, 1,710 lines)
│   │   ├── public/
│   │   └── design/                      (committed, never imported/bundled)
│   └── scripts/                         (demo_reset.mjs etc.)
├── docs/
│   ├── DEMO_STEPS.md, PRODUCT_AUDIT.md, PRODUCT_STATUS.md, SELF_TEST_GUIDE.md
│   ├── context/                         (WUNOMO_MASTER_CONTEXT.md, SESSION_LOG.md, ENGINEERING_HISTORY.md, STATUS_TABLE.md, GOTCHAS.md, WORKFLOW_RULES.md)
│   ├── design/
│   └── self_test_assets/
├── Document/                            (PDFs, pitch deck, YC materials — not app code)
├── marketing-site/                      (separate Next.js project, not part of this app)
├── employee_data.csv, sales_data.csv, pipeline_config.json, generate_dataops_project.py, tree.txt  (sample/scaffold, root level)
└── venv/                                (Python venv, excluded from analysis)
```

Line counts (backend, by top-level module, `.py` only, excluding `__pycache__`):

| Module | Lines |
|---|---|
| `api/` | 5,936 |
| `agent/` | 1,143 |
| `models/` | 1,047 |
| `modules/` | 9,547 |
| `services/` | 4,223 |
| `schemas/` | 408 |
| `scripts/` | 80 |
| `tests/` | 16,626 |
| root-level `.py` (`main.py`, `config.py`, `database.py`, `diagnose.py`, `fix_analytics*.py`, `patch_analytics.py`, `seed_approval.py`) | 468 |
| **backend total (excl. tests)** | **22,929 lines of application code (~239 files)** |
| `frontend/src` (.ts/.tsx) | 14,068 lines (~108 files) |

The test suite (16,626 lines) is larger than any single backend application module and roughly 40% the size of the entire backend application codebase combined.

---

## 2. ENDPOINTS

`main.py` mounts 23 routers, all under `/api/v1`, in this order (`main.py:103-151`). `redirect_slashes=False` (`main.py:59`) — `/x` and `/x/` are genuinely distinct routes throughout; several routers register both. Four ad-hoc, router-less endpoints also exist directly on `app`: `GET /health`, `/health/db`, `/health/models`, `/health/tasks` (`main.py:155-223`) — none carry an auth dependency.

### auth.py — `/api/v1/auth`
| Method | Path | Handler | @ | Auth | Body | Response |
|---|---|---|---|---|---|---|
|POST|/register|register|129|none|RegisterRequest|none|
|POST|/login|login|151|none|OAuth2PasswordRequestForm (form)|none|
|POST|/email-code/request|request_email_code|172|none|EmailCodeRequest|none|
|POST|/email-code/verify|verify_email_code|189|none|EmailCodeVerify|none|
|GET|/google/login-url|google_login_url|228|none|none|none|
|POST|/google/callback|google_callback|240|none|GoogleCallback|none|
|POST|/resolve-workspace|resolve_workspace|299|none|ResolveWorkspaceRequest|none|
|GET|/my-workspaces|my_workspaces|313|get_current_user|none|none|
|POST|/switch-workspace|switch_workspace_route|326|get_current_user|SwitchWorkspaceRequest|none|
|GET|/me|me|346|get_current_user|none|none|
|PATCH|/me|update_me|368|get_current_user|MeUpdate|none|

`get_current_user`, `require_permission(cap)`, `enforce_quota(resource)`, `enforce_agent_budget(agent_id)` all live here and are imported by nearly every other router.

### uploads.py — `/api/v1/uploads`
|POST|/|upload_file|21|get_current_user|`UploadFile` (multipart)|none|
|POST|/register|upload_and_register|32|require_permission("sources.create") + enforce_quota("data_sources")|`UploadFile` + `name` (multipart)|none|

### sources.py — `/api/v1/sources`
|GET|/|list_sources|49|get_current_user|none|none|
|POST|/|create_source|53|require_permission("sources.create") + enforce_quota("data_sources")|SourceCreate|none|
|POST|/test-connection|test_connection|62|require_permission("sources.create")|TestConnectionRequest|none|
|GET|/{id}|get_source|151|get_current_user|none|none|
|PUT|/{id}|update_source|164|require_permission("sources.create")|SourceUpdate|none|
|DELETE|/{id}|delete_source|181|require_permission("sources.delete")|none|none|
|POST|/{id}/profile|profile_source|201|require_permission("sources.profile")|none|none|
|POST|/{id}/sync|sync_source|205|require_permission("sources.profile")|none (query `mode`)|none|
|GET|/{id}/preview|preview|209|get_current_user|none|none|
|POST|/{id}/drift|detect_drift|213|require_permission("sources.profile")|none|none|

### pipelines.py — `/api/v1/pipelines`
|GET|/|list_pipelines|56|get_current_user|none|none|
|POST|/|create_pipeline|61|require_permission("pipelines.create")|PipelineCreate|none|
|GET|/{id}|get_pipeline|72|get_current_user|none|none|
|PUT|/{id}|update_pipeline|80|require_permission("pipelines.create")|PipelineUpdate|none|
|DELETE|/{id}|delete_pipeline|92|require_permission("pipelines.delete")|none|none|
|POST|/{id}/trigger|trigger_run|126|require_permission("pipelines.operate") + enforce_quota("pipeline_runs")|none|none|
|POST|/{id}/pause|pause_pipeline|140|require_permission("pipelines.operate")|none|none|
|POST|/{id}/activate|activate_pipeline|148|require_permission("pipelines.operate")|none|none|
|PUT|/{id}/schedule|set_schedule|156|require_permission("pipelines.create")|ScheduleUpdate|none|
|GET|/{id}/runs|get_run_history|166|get_current_user|none|none|
|POST|/{id}/backfill|backfill|175|require_permission("pipelines.operate")|BackfillRequest|none|

### runs.py — `/api/v1/runs`
|GET|/{pipeline_id}|get_runs|7|get_current_user|none|none|

**This is the only registered route prefix in the entire backend with zero test coverage anywhere** (see §8) and zero frontend callers anywhere (see §9) — orphaned on both sides.

### quality.py — `/api/v1/quality`
|GET|/|list_rules|20|get_current_user|none|none|
|POST|/|create_rule|25|require_permission("quality.manage")|RuleCreate|none|
|POST|/{pipeline_id}/run|run_checks|38|require_permission("quality.manage")|none|none|
|DELETE|/{rule_id}|delete_rule|43|require_permission("quality.delete")|none|none|

### incidents.py — `/api/v1/incidents`
|GET|/|list_incidents|39|get_current_user|none|none|
|POST|/|create_incident|94|require_permission("incidents.log")|IncidentCreate|none|
|GET|/{id}|get_incident|144|get_current_user|none|none|
|PUT|/{id}|update_incident|167|require_permission("incidents.resolve")|IncidentUpdate|none|
|POST|/{id}/resolve|resolve_incident|192|require_permission("incidents.resolve")|IncidentResolve|none|

### governance.py — `/api/v1/governance`
|GET|/lineage/{asset_name}|get_lineage|54|get_current_user|none|none|
|GET|/graph|get_full_graph|77|get_current_user|none|none|
|POST|/lineage/node|add_lineage_node|88|get_current_user|AddNodeRequest|none|
|POST|/lineage/edge|add_lineage_edge|108|get_current_user|AddEdgeRequest|none|
|GET|/contracts|list_contracts|134|get_current_user|none|none|
|GET|/contracts/{id}|get_contract|155|get_current_user|none|none|
|POST|/contracts|create_contract|176|require_permission("contracts.create")|CreateContractRequest|none|
|POST|/contracts/{id}/validate|validate_contract|196|require_permission("contracts.validate")|none — `ValidateContractRequest` is declared (line 46) but never used as a parameter, dead schema|none|
|GET|/audit|get_audit_trail|218|get_current_user|none|none|

### approvals.py — `/api/v1/approvals` — see §7 for full trace
|GET|""|list_pending_approvals|29|get_current_user|none|none|
|GET|/|list_pending_approvals (same fn, dual decorator)|30|get_current_user|none|none|
|GET|/merged|list_merged_approvals|43|get_current_user|none|none|
|GET|/{id}|get_approval|120|get_current_user|none|none|
|POST|/{id}/approve|approve_action|130|require_permission("approvals.manage")|ResolveRequest|none|
|POST|/{id}/reject|reject_action|162|require_permission("approvals.manage")|ResolveRequest|none|

### analytics.py — `/api/v1/analytics`
|GET|/health|analytics_health|41|get_current_user|none|none|
|GET|""|get_analytics_overview|49|get_current_user|none|none|
|GET|/recent-runs|get_recent_runs|144|get_current_user|none|none|
|GET|/pipelines|get_pipeline_analytics|181|get_current_user|none|none|
|GET|/quality|get_quality_trends|223|get_current_user|none|none|
|GET|/kpis|get_kpis|274|get_current_user|none|none|
|POST|/kpis|record_kpi|327|get_current_user|RecordKpiRequest|none|
|GET|/usage|get_usage_metrics|359|get_current_user|none|none|

`RecordUsageRequest` (analytics.py:31-35) is defined but unused — no `POST /usage` exists.

### transformations.py — `/api/v1/transformations`
|POST|/generate|generate_transform|51|get_current_user|GenerateRequest|none|
|POST|/generate/sql|generate_sql|80|get_current_user|GenerateRequest|none|
|POST|/generate/pandas|generate_pandas|95|get_current_user|GenerateRequest|none|
|POST|/run/sql|run_sql|110|require_permission("transforms.execute")|RunSqlRequest|none|
|POST|/run/sql/dry-run|dry_run_sql|134|get_current_user|RunSqlRequest|none|
|POST|/run/pandas|run_pandas|144|require_permission("transforms.execute")|RunPandasRequest|none|
|POST|/preview/pandas|preview_pandas|167|get_current_user|RunPandasRequest|none|
|POST|/explain|explain_code|177|get_current_user|ExplainRequest|none|
|GET|/runs|list_transform_runs|187|get_current_user|none|none|

### catalog.py — `/api/v1/catalog`
|GET|/|get_catalog|25|get_current_user|none|none|

### cicd.py — `/api/v1/cicd`
|POST|/webhook|github_webhook|93|none (HMAC `X-Hub-Signature-256`, not JWT)|GitHubPushPayload|`response_model=WebhookResponse`|
|GET|/commits|list_commits|193|get_current_user|none|`response_model=list[PipelineCommitResponse]`|
|GET|/commits/{id}|get_commit|208|get_current_user|none|`response_model=PipelineCommitResponse`|
|POST|/commits/{id}/approve|approve_deployment|228|require_permission("cicd.approve")|none|none|
|POST|/commits/{id}/reject|reject_deployment|266|require_permission("cicd.approve")|none|none|
|GET|/deployments|list_deployments|297|get_current_user|none|`response_model=list[PipelineDeploymentResponse]`|
|GET|/deployments/{id}|get_deployment|314|get_current_user|none|`response_model=PipelineDeploymentResponse`|
|POST|/deployments/{id}/record-run|record_post_deploy_run|340|get_current_user|RunResultPayload|none|
|GET|/deployments/{id}/health|get_deployment_health|387|get_current_user|none|none|
|GET|/incidents|list_incidents|443|get_current_user|none|none|
|PATCH|/incidents/{id}/resolve|resolve_incident|476|require_permission("cicd.incidents.resolve")|none|none|
|GET|/status/summary|cicd_status_summary|505|get_current_user|none|none|

(`list_incidents`/`resolve_incident` names collide with `incidents.py`'s functions — different modules, no functional bug.)

### chat.py — `/api/v1/chat` — see §5 for full trace
|POST|/|chat|105|enforce_quota("ai_credits")|ChatRequest|none|
|GET|/sessions|list_sessions|311|get_current_user|none|none|
|GET|/sessions/{id}/history|get_history|450|get_current_user|none|none|
|DELETE|/sessions/{id}|delete_session|465|get_current_user|none|none|

### onboarding.py — `/api/v1/onboarding`
|POST|/|submit_onboarding|26|get_current_user|OnboardingRequest|none|
|GET|/|get_onboarding|59|get_current_user|none|none|

### team.py — `/api/v1/team`
|POST|/invites|create_team_invite|29|require_permission("team.manage") + enforce_quota("team_members")|InviteCreate|none|
|GET|/invites|list_team_invites|58|require_permission("team.manage")|none|none|
|DELETE|/invites/{id}|revoke_team_invite|79|require_permission("team.manage")|none|none|
|GET|/invites/verify|verify_team_invite|98|none (public)|none|none|
|POST|/invites/accept|accept_team_invite|108|none (public)|InviteAccept|none|
|GET|/members|list_team_members|121|get_current_user|none|none|
|PATCH|/members/{user_id}/role|change_member_role|150|require_permission("team.manage")|RoleChange|none|
|DELETE|/members/{user_id}|remove_team_member|183|require_permission("team.manage")|none|none|

### billing.py — `/api/v1/billing` — **half-built by design, see flags below**
|GET|/usage|get_usage|15|get_current_user|none|none|
|GET|/plans|list_plans|25|none (public)|none|none|
|GET|/plan|get_current_plan|31|get_current_user|none|none|
|POST|/change-plan|change_plan|36|require_permission("billing.manage")|PlanChange|none|
|POST|/checkout|create_checkout|56|require_permission("billing.manage")|none|none|
|POST|/webhook|stripe_webhook|61|none (public)|none|none|

### settings.py — `/api/v1/settings`
|GET|/|get_settings|20|get_current_user|none|none|
|PATCH|/|patch_settings|28|require_permission("settings.manage")|SettingsUpdate|none|
|POST|/test-slack-webhook|test_slack_webhook|46|require_permission("settings.manage")|TestSlackWebhookRequest|none|

### api_keys.py — `/api/v1/api-keys`
|POST|/|create_key|14|require_permission("api_keys.manage")|ApiKeyCreate|none|
|GET|/|list_keys|27|require_permission("api_keys.manage")|none|none|
|DELETE|/{id}|revoke_key|35|require_permission("api_keys.manage")|none|none|

### tasks.py — `/api/v1/tasks`
|GET|/|list_tasks|319|get_current_user|none|none|
|GET|/all|list_all_tenant_tasks|343|require_permission("tasks.manage_all")|none|none|
|GET|/active|list_active_tasks|422|get_current_user|none|none|
|GET|/{id}|get_task|530|get_current_user|none|none|
|POST|/|create_task|553|enforce_quota("ai_credits")|CreateTaskRequest|none|
|PATCH|/{id}/steps|edit_task_steps|678|get_current_user|EditStepsRequest|none|
|POST|/{id}/approve-plan|approve_task_plan|792|get_current_user|none|none|
|POST|/{id}/reject-plan|reject_task_plan|824|get_current_user|none|none|
|POST|/{id}/advance|advance_task|848|get_current_user|none|none|
|POST|/{id}/resume|resume_task_endpoint|890|require_permission("approvals.manage")|ResolveStepRequest|none|
|POST|/{id}/reject-step|reject_task_step_endpoint|926|require_permission("approvals.manage")|ResolveStepRequest|none|
|POST|/{id}/cancel|cancel_task_endpoint|957|get_current_user|none|none|

(`/all` and `/active` are deliberately declared before `/{task_id}` — comment at 340-342 — correct ordering.)

### agents.py — `/api/v1/agents`
|POST|/{id}/sources/{source_id}|grant_source|84|require_permission("agents.manage")|none|none|
|DELETE|/{id}/sources/{source_id}|revoke_source|98|require_permission("agents.manage")|none|none|
|GET|/{id}/sources|list_agent_sources|114|require_permission("agents.manage")|none|none|
|GET|/schedules|list_all_schedules|180|require_permission("agents.manage")|none|none|
|POST|/{id}/schedules|create_schedule|239|require_permission("agents.manage")|ScheduleCreate|none|
|GET|/{id}/schedules|list_schedules|306|require_permission("agents.manage")|none|none|
|POST|/{id}/schedules/{sid}/reactivate|reactivate_schedule|326|require_permission("agents.manage")|none|none|
|DELETE|/{id}/schedules/{sid}|delete_schedule|358|require_permission("agents.manage")|none|none|
|GET|/{id}/quota|get_agent_quota|375|require_permission("agents.manage")|none|none|
|POST|/{id}/offboard|offboard_agent|395|require_permission("agents.manage")|none|none|
|POST|/|hire_agent|539|require_permission("agents.manage")|AgentHire|none|
|GET|/selectable|list_selectable_agents|625|get_current_user|none|none|
|GET|/|list_agents|670|require_permission("agents.manage")|none|none|

### projects.py — `/api/v1/projects`
|POST|/|create_project|49|require_permission("agents.manage")|ProjectCreate|none|
|GET|/|list_projects|67|require_permission("agents.manage")|none|none|
|PATCH|/{id}|rename_project|80|require_permission("agents.manage")|ProjectRename|none|
|DELETE|/{id}|delete_project|97|require_permission("agents.manage")|none|none|
|GET|/{id}/agents|list_project_agents|126|require_permission("agents.manage")|none|none|
|GET|/{id}/channels|list_project_channels|142|require_permission("agents.manage")|none|none|

### channels.py — `/api/v1/channels`
|POST|/|create_channel|53|get_current_user|ChannelCreate|none|
|GET|/|list_channels|75|get_current_user|none|none|
|GET|/{id}|get_channel|105|get_current_user|none|none|
|POST|/{id}/members/users/{uid}|add_user_member|130|get_current_user|none|none|
|DELETE|/{id}/members/users/{uid}|remove_user_member|152|get_current_user|none|none|
|POST|/{id}/members/agents/{aid}|add_agent_member|195|get_current_user|none|none|
|DELETE|/{id}/members/agents/{aid}|remove_agent_member|221|get_current_user|none|none — **has no `return` statement at all; falls off the end, FastAPI serializes `null`.** Not caught by `test_channels.py` (asserts status code only, never inspects body).|
|POST|/{id}/upload|upload_to_channel|236|require_permission("sources.create") + enforce_quota("data_sources")|`UploadFile` + `message` (multipart)|none — contains a second, unreachable `return` statement at line 313, dead code after the real return at 304-311.|

### Stub / dead-handler flags

Grepped every router file for `TODO`, `FIXME`, `NotImplementedError`, and a lone `pass` body: **none found.** Nothing in `api/v1/` literally matches those criteria. The real, honest stubs are:

| Route | Behavior | Tested? |
|---|---|---|
| `POST /billing/change-plan` | Unconditionally raises `HTTPException(501, "Self-serve plan changes are disabled until Stripe billing is live")`, never reads the request body | Yes — `test_billing_service.py` (3 tests explicitly named around this being an "honest stub") |
| `POST /billing/checkout` | Unconditional `HTTPException(501, ...)` | Yes — `test_billing_service.py:113` |
| `POST /billing/webhook` | Unconditional `HTTPException(501, ...)`, no auth dependency, ignores payload | Yes — `test_billing_service.py:116` |

These are **deliberate, documented, tested 501s** (Stripe integration not built), not forgotten code — the frontend agrees (`team/page.tsx:345` shows an honest "Coming soon" string for billing).

---

## 3. MODELS

35 non-`Tenant` SQLAlchemy model classes across `models/all_models.py` (892 lines), `models/approval_model.py` (4-line re-export shim, no new class), `models/cicd.py` (154 lines). Every enum in `all_models.py` follows `UPPERCASE_MEMBER = "lowercase_value"`; every enum in `cicd.py` uses lowercase members, as CLAUDE.md documents — confirmed, and `cicd.py` additionally **redeclares `IncidentSeverity`/`IncidentStatus` as separate classes with the same names** as `all_models.py`'s own (different casing on the *values*), a real name-collision risk for any code importing both unnamespaced.

### Core tables (full FK graph)

| Table | Key columns (types/nullability) | FKs | Notes |
|---|---|---|---|
| `tenants` | id PK, name NOT NULL, slug UNIQUE NOT NULL, plan, is_active, settings JSON, created/updated_at | — (root) | |
| `users` | id PK, tenant_id NOT NULL, email NOT NULL, hashed_password nullable, google_id nullable idx, role, is_active, personality_mode/operation_mode enums, theme | `tenant_id → tenants.id` | UNIQUE(tenant_id, email) |
| `data_sources` | id PK, tenant_id NOT NULL, name NOT NULL, source_type enum NOT NULL, connection_config JSON NOT NULL, schema_snapshot JSON, tags JSON | `tenant_id → tenants.id` | |
| `pipelines` | id PK, tenant_id NOT NULL, source_id nullable, status enum, schedule_cron, pipeline_config JSON, sla_minutes, retry_policy JSON, version | `tenant_id → tenants.id`, `source_id → data_sources.id` | |
| `pipeline_runs` | id PK, pipeline_id NOT NULL, tenant_id NOT NULL (bare), status enum, rows_processed/failed, quality_score, run_logs JSON | `pipeline_id → pipelines.id` | **tenant_id has no FK** |
| `quality_rules` | id PK, pipeline_id nullable, tenant_id NOT NULL (bare), rule_type, rule_config JSON, pass/fail_count | `pipeline_id → pipelines.id` (nullable) | **tenant_id has no FK**; pipeline FK optional |
| `incidents` | id PK, tenant_id NOT NULL (bare), pipeline_id/run_id nullable, severity/status enums, root_cause | `pipeline_id → pipelines.id`, `run_id → pipeline_runs.id` (both nullable) | **tenant_id has no FK**; `pipeline_delete` deliberately nulls `pipeline_id` to preserve incidents |
| `lineage_nodes` | id PK, tenant_id NOT NULL (bare), node_type, name NOT NULL, node_metadata JSON | none | **no FK of any kind** |
| `lineage_edges` | id PK, tenant_id NOT NULL (bare), upstream/downstream_id NOT NULL | both `→ lineage_nodes.id` | anchors only to another un-FK'd table |
| `audit_logs` | id PK, tenant_id NOT NULL (bare, explicitly by design), agent_id nullable, action NOT NULL, payload JSON | none | comment: must never fail an insert over referential integrity |
| `approval_requests` | id PK, tenant_id NOT NULL indexed (bare), user_id/session_id NOT NULL (bare), status enum indexed, action_args/execution_result JSON | none | see §7 |
| `chat_messages` | id PK, tenant_id/user_id/session_id NOT NULL (all bare), agent_id/mentioned_agent_id nullable (bare), role String(20), content Text NOT NULL, tool_calls/msg_metadata JSON | none | see §5; no indexes despite heavy `session_id`/`tenant_id` filtering |
| `data_contracts` | id PK, tenant_id NOT NULL (bare), producer_source_id nullable, schema_expectations/quality_conditions JSON | `producer_source_id → data_sources.id` (nullable) | |
| `usage_metrics` | id PK, tenant_id NOT NULL (bare), metric_type NOT NULL, value Float NOT NULL, pipeline_id plain column | none | pipeline_id not even wrapped in FK() |
| `kpi_values` | id PK, tenant_id NOT NULL (bare), kpi_name, value Float NOT NULL | none | |
| `llm_usage_events` | id PK, tenant_id NOT NULL indexed (bare), task_id/agent_id nullable indexed (bare) | none | deliberate — a failed plan generation logs under a task_id whose Task row never persists |
| `onboarding_profiles` | id PK, tenant_id NOT NULL UNIQUE, user_id NOT NULL | `tenant_id → tenants.id`, `user_id → users.id` | real FK |
| `user_workspace_preferences` | **email is the PK** (not a synthetic id), tenant_id NOT NULL | `tenant_id → tenants.id` | real FK |
| `email_login_codes` | id PK, email NOT NULL indexed, code_hash, intended_tenant_id nullable | `intended_tenant_id → tenants.id` (nullable) | **has no tenant_id column at all** — global by design, keyed by email across tenants |
| `transform_runs` | id PK, tenant_id NOT NULL indexed (bare, comment: "accepted consciously"), source_id indexed plain column (not FK) | none | |
| `team_invites` | id PK, tenant_id NOT NULL, invited_by_user_id NOT NULL, token_hash UNIQUE | `tenant_id → tenants.id`, `invited_by_user_id → users.id` | real FK |
| `api_keys` | id PK, tenant_id NOT NULL, key_hash UNIQUE, created_by_user_id NOT NULL | `tenant_id → tenants.id`, `created_by_user_id → users.id` | real FK |
| `agent_instances` | id PK, tenant_id NOT NULL indexed, employee_type/personality/operation_mode/status enums, model NOT NULL | `tenant_id → tenants.id` | UNIQUE(tenant_id, name); real FK |
| `agent_sources` | id PK, agent_id NOT NULL indexed, source_id NOT NULL indexed | `agent_id → agent_instances.id`, `source_id → data_sources.id` | UNIQUE(agent_id, source_id); **no tenant_id column at all**, but both parents are tenant-FK'd |
| `projects` | id PK, tenant_id NOT NULL indexed, name NOT NULL | `tenant_id → tenants.id` | UNIQUE(tenant_id, name); real FK |
| `project_agents` | id PK, project_id/agent_id NOT NULL indexed | `project_id → projects.id`, `agent_id → agent_instances.id` | **no tenant_id column**, both parents tenant-FK'd |
| `channels` | id PK, tenant_id NOT NULL indexed, project_id nullable indexed | `tenant_id → tenants.id`, `project_id → projects.id` | real FK |
| `channel_users` | id PK, channel_id/user_id NOT NULL indexed | `channel_id → channels.id`, `user_id → users.id` | UNIQUE(channel_id, user_id); **no tenant_id column** |
| `channel_agents` | id PK, channel_id/agent_id NOT NULL indexed | `channel_id → channels.id`, `agent_id → agent_instances.id` | UNIQUE(channel_id, agent_id); **no tenant_id column** |
| `tasks` | id PK, tenant_id/user_id NOT NULL, agent_id nullable, task_shape/status enums NOT NULL, step_budget_max NOT NULL | `tenant_id → tenants.id`, `user_id → users.id`, `agent_id → agent_instances.id`, `plan_approved_by → users.id`, `originating_schedule_id → scheduled_agent_tasks.id` (ondelete SET NULL) | real FK; composite index `(status, updated_at)` |
| `task_steps` | id PK, task_id NOT NULL indexed, step_index/description NOT NULL, source/status enums NOT NULL | `task_id → tasks.id`, `approval_request_id → approval_requests.id` (nullable) | **no tenant_id column**, tenant scoping via `task_id` parent only |
| `scheduled_agent_tasks` | id PK, tenant_id NOT NULL indexed, agent_id NOT NULL indexed, task_shape/description/tool_name/tool_args/schedule_cron NOT NULL, active indexed | `tenant_id → tenants.id`, `agent_id → agent_instances.id`, `created_by_user_id → users.id` | real FK |
| `pipeline_commits` (cicd.py) | id PK, tenant_id NOT NULL indexed (bare), pipeline_id nullable, ci_status/gate_decision Postgres ENUMs, trigger_time `DateTime(timezone=True)` | `pipeline_id → pipelines.id` (ondelete CASCADE) | tz-aware columns — the documented Hard Rule 3 exception |
| `pipeline_deployments` (cicd.py) | id PK, tenant_id NOT NULL indexed (bare), pipeline_id/commit_id NOT NULL, status Postgres ENUM | `pipeline_id → pipelines.id`, `commit_id → pipeline_commits.id` (both CASCADE) | tz-aware |
| `cicd_incidents` (cicd.py) | id PK, tenant_id NOT NULL indexed (bare), pipeline_id/deployment_id NOT NULL, severity/status Postgres ENUMs | `pipeline_id → pipelines.id`, `deployment_id → pipeline_deployments.id` (both CASCADE) | tz-aware |

### Tenant-isolation gap summary

Of the 35 non-`Tenant` models, **19 either have a bare (non-FK'd) `tenant_id` column or none at all**. Breaking that down:

- **8 have zero FK path to any tenant-scoped table whatsoever** and rely entirely on every hand-written query filtering `tenant_id` correctly: `lineage_nodes`, `audit_logs`, `approval_requests`, `chat_messages`, `usage_metrics`, `kpi_values`, `llm_usage_events`, `transform_runs`. Several of these (`audit_logs`, `llm_usage_events`, `transform_runs`) carry explicit code comments stating this is a conscious tradeoff (an audit/metering insert must never fail on a referential-integrity error).
- **11 more have a real FK to a *non-tenant* parent** that itself resolves to a tenant (e.g. `pipeline_runs.pipeline_id → pipelines`, `agent_sources` via either of its two FKs) — this gives an indirect path, but nothing in the schema enforces that a row's own `tenant_id` value actually agrees with its parent's `tenant_id`; a mismatched pair is not rejected by any DB constraint.
- **12 models have a real, non-nullable `ForeignKey("tenants.id")`**: `users`, `data_sources`, `pipelines`, `onboarding_profiles`, `user_workspace_preferences`, `team_invites`, `api_keys`, `agent_instances`, `projects`, `channels`, `tasks`, `scheduled_agent_tasks`.

This is the "multi-tenant by convention, not enforcement" design CLAUDE.md itself declares — verified accurate, not aspirational.

---

## 4. AGENT LAYER

**Exactly one `StateGraph` exists in the entire backend**: `agent/dataops_agent.py:357`, inside `build_agent()`. `modules/orchestration/task_planner.py`/`task_executor.py` (the "Wunomo Projects" layer) build no graph at all.

### Topology
State: `AgentState` TypedDict (204-218) — `messages` (reducer `operator.add`), `tenant_id`, `user_id`, `session_id`, `caller_role`, `personality_mode`, `operation_mode`, `pending_approvals`, `role_denied`, `scope_denied`, `iteration_count`, `context`, `system_prompt`, `agent_id`.

Nodes: `inject_system` (248) → `agent` (266, async, calls the LLM, force-overwrites tenant/user/session/task/agent IDs on outgoing tool calls, runs role- and scope-denial checks) → `approval_gate` (333, checks risk tier vs. `requires_approval()`) → `tools` (`ToolNode(allowed_tools)`, 361).

Edges: `inject_system → agent` (363, unconditional) → `approval_gate` (364, unconditional) → conditional (365, via `should_continue`) → `tools` or `END` → `tools → agent` (366, loop back).

```python
def should_continue(state):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "end" if state.get("pending_approvals") else "tools"
    return "end"
```

`get_agent()` (372-400) caches **compiled graph objects** keyed by `tenant_id:agent_id:personality:operation:model:config_version` — separate agents/tenants get separate graph objects, not shared state within one invocation.

### Tools
All 40 tools bound in one call: `llm_with_tools = llm.bind_tools(allowed_tools)` (`dataops_agent.py:235`), `allowed_tools` defaulting to `ALL_TOOLS` (`agent/tools/__init__.py:10-14`): 7 ingestion, 4 transformation, 5 quality, 7 orchestration, 6 observability, 5 governance, 5 reporting, 1 cicd. Import-time assertion (27-31) crashes the process at boot if any tool lacks an RBAC `TOOL_CAPABILITIES` entry. `task_planner.py` uses a narrower per-`TaskShape` allowlist, but those tools are called directly by `task_executor.py`, never via `bind_tools` — the planner LLM sees their JSON schemas as text and returns a plan, not a live tool call.

### LLM invocation
`services/llm_service.py`: `_provider_for_model(model)` → `"gemini" if model.startswith("gemini") else "groq"` (74-87); `_build_llm()` (180-196) routes to `ChatGoogleGenerativeAI` or `ChatGroq` accordingly. The agent graph's actual fallback mechanism is a custom `_TimeoutFallbackChatModel` (259-328), not LangChain's `RunnableWithFallbacks`:

```python
async def ainvoke(self, messages, *args, **kwargs):
    try:
        response = await asyncio.wait_for(self._primary.ainvoke(messages, *args, **kwargs), timeout=self._timeout)
        return response
    except Exception as e:
        response = await self._fallback.ainvoke(messages, *args, **kwargs)
        return response
```
Trigger: any exception from the primary, or exceeding `PRIMARY_LLM_TIMEOUT_SECONDS` (30s) — whichever first. If even building the primary client raises, `get_llm_for_agent()` routes straight to the fallback with `force_used_fallback=True`. A separate function, `invoke_llm()` (used by the task planner/executor and context summarization), has its own primary/fallback try/except plus a `@retry(stop_after_attempt(3), wait_exponential(...))` decorator.

### Multi-agent chaining — explicit answer

**No.** A single `run_agent()` call resolves exactly one `AgentInstance`, builds/fetches exactly one compiled graph, with exactly one LLM-calling node bound once to one system prompt and one tool set. The loop re-invokes the *same* node repeatedly; it does not route between personas.

```python
# dataops_agent.py:440-443
agent = get_agent(
    personality_mode, operation_mode, tenant_id=tenant_id, primary_model=primary_model,
    agent_id=agent_id, agent_name=agent_name, allowed_tools=allowed_tools, config_version=config_version,
)
```
```python
# dataops_agent.py:221-235
def build_agent(personality=PersonalityMode.ENGINEER, operation=OperationMode.ASSISTED, primary_model=None,
                 agent_name="AXIOM", allowed_tools=None):
    allowed_tools = ALL_TOOLS if allowed_tools is None else allowed_tools
    llm = get_llm_for_agent(temperature=0.0, primary_model=primary_model) if primary_model else get_llm_for_agent(temperature=0.0)
    llm_with_tools = llm.bind_tools(allowed_tools)
```
Channels can have multiple agents as *members*, and `@mention` routing (`services/channel_routing.py:104`) picks which single agent answers a given message — that's cross-*request* routing (one `run_agent()` call per HTTP POST, each resolving one agent), not chaining inside one graph invocation. `task_executor.py` similarly calls tools directly (`_call_tool()`, 550-584) against the tool object, "not through the agent's ToolNode/LangGraph machinery" per its own docstring — no LLM reasoning happens per step there either. **No code path anywhere feeds one agent's output as another distinct agent persona's input within a single invocation.**

---

## 5. CHAT — end-to-end trace of `POST /api/v1/chat/`

### Call chain
1. `enforce_quota("ai_credits")` → `get_current_user` (JWT decode + DB re-read of `is_active`/`role`) → `get_quota_status()` — 402 if exceeded.
2. Channel-id check (`select(Channel)`).
3. **Channel branch**: membership check → `resolve_channel_message_target()` (`channel_routing.py:104`) → `load_agent_channel_context()` (`channel_routing.py:64`).
4. **Private-session branch**: ownership check → most-recent-summary query → up-to-200-row raw history query → resolve tenant's active `AgentInstance`.
5. `enforce_agent_budget(agent_id)` → `get_agent_quota_status()` — 402 if exceeded.
6. `window_and_summarize()` (`dataops_agent.py:528`) — if history > 12 messages, calls `invoke_llm()` to refresh a persisted rolling summary.
7. `run_agent()` (`dataops_agent.py:403`) → resolves/builds the graph (§4) → `agent.ainvoke({...}, config={"recursion_limit": AGENT_RECURSION_LIMIT})` → runs the full graph loop described in §4 → `content_as_text()` normalizes the final response.
8. Second DB session: persists any `pending_approvals` as `ApprovalRequest` rows, extracts tool trace, conditionally persists a new summary `ChatMessage`, persists the user and assistant `ChatMessage` rows, commits.
9. Returns a plain dict.

### Streaming vs. buffered
**Fully buffered.** Repo-wide grep for `StreamingResponse`, `EventSourceResponse`, `text/event-stream`, `WebSocket`, `.astream(` returns zero matches anywhere in the backend. The handler is `async def chat(...)` returning a plain dict; `run_agent()` calls the graph's non-streaming `.ainvoke()`, not `.astream()`/`.astream_events()`. Nothing streams — the entire response (text, tool trace, provider, pending approvals) is assembled in memory before the single `return`.

### Session/history persistence
Table: `chat_messages` only — **there is no separate `ChatSession` table**; a "session" is purely the `session_id` grouping key. History is loaded fresh from the DB on **every single request** — no in-memory or Redis cache of conversation content (the only cache in this path is `dataops_agent.py`'s compiled-*graph-object* cache, unrelated to chat content). Writes happen inline in the route handler (`chat.py`), not through a dedicated service function.

### ChatMessage — what it actually stores

| Field | Type | Populated by |
|---|---|---|
| id | String PK | UUID |
| tenant_id, user_id | String NOT NULL | JWT claims |
| session_id | String NOT NULL | client-supplied or generated |
| agent_id | String, nullable, no FK | resolved `AgentInstance.id`; set only on assistant/summary rows |
| mentioned_agent_id | String, nullable, no FK | set only on the user row, only in a channel with a resolved `@mention` |
| role | String(20), unconstrained | `"user"` / `"assistant"` / `"summary"` — a plain string, not an enum |
| content | Text NOT NULL | the message / LLM response / summary text |
| personality_mode, operation_mode | String(50) | from `ChatRequest` |
| tool_calls | JSON, default list | tool trace, assistant row only |
| msg_metadata | JSON, default dict | **never set anywhere in `chat.py` — always `{}`, dead field for this endpoint** |
| created_at | DateTime, naive UTC | `datetime.utcnow()` |

`ChatResponse` schema exists in `schemas/chat_schema.py` but the route has **no `response_model=` declared** — the returned dict matches its shape by construction only, not by runtime validation.

---

## 6. CELERY

No `task_routes` config exists anywhere and no task passes `queue=` — **every task runs on Celery's default queue.**

| Task | File:line | Retry policy | Progress reporting |
|---|---|---|---|
| `execute_pipeline_run` | tasks.py:12 | `max_retries=3, default_retry_delay=60` | **Yes** — 3 intermediate `DAGManager.update_run_status(RUNNING, log_entry=...)` commits before the terminal SUCCESS/FAILED write |
| `execute_scheduled_pipeline_run` | tasks.py:160 | same | same (shared `_execute_run()`) |
| `check_scheduled_pipelines` | tasks.py:184 | same | terminal-only (dispatch loop) |
| `advance_active_tasks` | tasks.py:265 | same | terminal-only (dispatch loop) |
| `advance_one_task` | tasks.py:344 | same | Celery task itself: terminal-only; the work it dispatches to (`task_executor.execute_next_step()`) does update `TaskStep.status` incrementally through the DB |
| `check_scheduled_agent_tasks` | tasks.py:384 | same | terminal-only |
| `fire_scheduled_agent_task` | tasks.py:433 | same | terminal-only, single outcome per invocation |
| `check_all_freshness` | tasks.py:460 | **none configured** | terminal-only — one `db.commit()` at the very end of the whole tenant loop; a mid-run crash loses everything processed so far |
| `run_anomaly_detection` | tasks.py:547 | none | **placeholder** — docstring literally says "Placeholder — full implementation in Phase 3," logs only, no DB writes |
| `generate_daily_reports` | tasks.py:558 | none | **placeholder**, same as above |
| `run_ci_pipeline` | cicd_tasks.py:197 | `max_retries=2, default_retry_delay=30` | **Yes** — writes `ci_status=running` and commits before running checks, then writes terminal state |
| `deploy_pipeline` | cicd_deployment.py:12 | `max_retries=2` (retry called with explicit `countdown=30`) | Sets `status=deploying` via `flush()` only (not committed, invisible to other sessions) before the terminal commit — functionally no externally-observable intermediate state |
| `check_post_deploy_health` | cicd_monitor.py:20 | **none configured**, not even `bind=True`, no try/except at all | writes only when the monitoring window closes |

**Beat schedule** (`celery_app.py:27-77`): freshness check 15min, anomaly detection 1hr, scheduled-pipeline check 1min, active-task advance 1min, scheduled-agent-task check 1min, daily reports 24hr, CI/CD post-deploy health 60s. One entry (`cicd-post-deploy-monitor`, 300s) is dead/commented-out — matches a pre-existing known issue in `docs/context/STATUS_TABLE.md`.

---

## 7. APPROVALS

### Lifecycle
- **Creation**: two real sites. `PolicyEngine.create_request()` (`policy_engine.py:145-155`) — the canonical path, reached from the agent's `request_approval` tool and from `task_executor.py`'s mid-task approval gate. And a second, independent direct-constructor path at `chat.py:244-253`, triggered when the LangGraph `approval_gate_node` intercepts a risky tool call mid-turn — this one omits explicit `status=`/`created_at=`, relying on column defaults.
- **Storage**: `approval_requests` table (§3) — no FKs at all, `SAEnum(ApprovalStatus)` with values `PENDING/APPROVED/REJECTED/EXECUTED/FAILED`. `models/approval_model.py` is a pure re-export, not a second definition (no drift risk). The Alembic migration matches the model column-for-column.
- **Listing**: `GET /approvals` / `/approvals/` → `PolicyEngine.list_pending()` → `select(ApprovalRequest).where(tenant_id=..., status=PENDING).order_by(desc(created_at))`, serialized by a defensive `_serialize()` (guards every nullable field). **No `response_model=` is declared** — the route returns a plain dict, and `schemas/approval_schema.py`'s `ApprovalResponse` is dead code (zero references anywhere outside its own file).
- **Resolution**: `POST /approve` / `/reject` → `PolicyEngine.approve()`/`reject()` — reject if not `PENDING`; approve sets `APPROVED` then calls `execute_approved_action()` (dispatches through a hardcoded `TOOL_REGISTRY` via `importlib`) and writes a final `EXECUTED`/`FAILED` status in a second commit. Valid transitions: `PENDING → APPROVED → (EXECUTED|FAILED)` or `PENDING → REJECTED`; nothing moves a resolved row back to `PENDING`.
- **`agent/approval_executor.py`** (a separate `execute_tool_call()` dispatch path using `ALL_TOOLS` instead of `TOOL_REGISTRY`) is **confirmed dead code** — zero references anywhere in the app, tests, or frontend-triggered flow.

### The claimed `GET /api/v1/approvals/` 500 bug

**Could not be reproduced.** This was investigated hard, not just read past:

- The existing test suite for this path (`test_approvals_merged.py`) passes 6/6 against the real dev Postgres DB.
- Confirmed the one genuine gap: no test anywhere exercises the plain list endpoint's authenticated 200 path — `test_api.py::test_approvals_requires_auth` only checks the 401 case, and `test_approvals_merged.py` only ever calls `/approvals/merged`, never the plain list.
- Wrote and ran (then deleted, repo confirmed clean) targeted repro tests: an empty tenant, a row created via `PolicyEngine.create_request()`, a raw `ApprovalRequest(...)` matching `chat.py:244`'s no-explicit-status construction exactly, hitting the endpoint via both `/approvals` and `/approvals/`, and a raw `curl` against the live running container. **All returned 200.**
- Queried the real dev database directly: 2,482 real `approval_requests` rows across all 5 statuses (1405 PENDING, 490 APPROVED, 241 REJECTED, 341 EXECUTED, 5 FAILED), no NULLs in `status`. Ran the exact `list_pending()` query + `_serialize()` + `json.dumps()` against every one of the 1405 live PENDING rows, outside the exception handler — zero failures.

**Conclusion: no triggering condition was found.** The only real weak point identified is `list_pending()`'s blanket `except Exception` (`policy_engine.py:200-202`), which converts *any* unexpected failure (a dropped connection, pool exhaustion, a future schema drift) into a 500 rather than something more specific — a design smell, not a bug that fires under any state found in the live system or in code. If a specific stack trace or triggering tenant/row exists, it wasn't reproducible from current code or current data — this report states that plainly rather than inventing a root cause.

---

## 8. TESTS

- **85 files** under `backend/tests/` (83 `test_*.py` + `conftest.py` + `__init__.py`), **634 `def test_...` functions**, **655 collected test items** (the +21 gap is one parametrized test in `test_permission_matrix.py` expanding across ~21 endpoint/capability combinations).
- **Running the suite outside Docker fails universally** — `backend/.env` hardcodes Docker-internal hostnames (`redis`, `postgres`) that don't resolve from a bare Windows host process, even though the containers publish the same ports to `localhost`. This is the exact mirror image of Hard Rule 4 in CLAUDE.md.
- **Running it the documented way** (`docker compose exec backend python -m pytest tests/ -q`) made real progress: **≈277 of 655 tests (~42%) passed, zero failures, zero errors observed**, before the run had to be stopped due to session time limits — it did not finish, and no final pass/fail count could be obtained. The slowdown is consistent with CLAUDE.md's own documented Gemini/Groq daily-quota ceilings — some test appears to make a real LLM call and hit rate-limit backoff.

### Modules with genuinely zero test coverage
- **`api/v1/runs.py`** and its only consumer, `modules/orchestration/run_tracker.py` — the single backend route prefix with zero references anywhere in `tests/`.
- **`agent/approval_executor.py`** — dead code, unreferenced anywhere, not merely untested.
- **`agent/tools/{governance,ingestion,orchestration,quality,reporting}_tools.py`** — the tool-*wrapper* functions themselves are never invoked in a test (only their *names* get enumerated for permission-gate checks); the service layer underneath each is tested separately.
- **`modules/ingestion/connectors/{postgres,mysql,api,gsheets}_connector.py`** — every test source uses `source_type: "csv"`, so the connector factory's other branches never execute in tests.
- **`modules/ingestion/connectors/csv_connector.py`** — dead code in production too; `ConnectorManager` routes CSV through `FileConnector` instead, so this file is unreachable from both the app and the tests.
- **`modules/ingestion/schema_profiler.py`** — one test hand-constructs a dict matching its output shape but never calls it.
- **`modules/quality/test_runner.py`**, **`services/celery_app.py`**, **`schemas/*`** (all 10 schema files — validated only indirectly through ~75 endpoint tests, never directly).

Best-covered areas: `modules/orchestration/task_executor.py`/`task_planner.py` (7+ dedicated test files), and the `services/*` layer (nearly 1:1 test-file-per-service).

---

## 9. FRONTEND

Real, substantial Next.js 15 app — 14,068 lines across ~108 files, one typed API client (`src/lib/api.ts`, 1,710 lines, 126 exported functions; no raw `fetch()` used anywhere else in the app).

### Routes

**11 routes are deliberate retirements**, each a small (5-18 line) `RetiredRouteRedirect` component with an explained reason, not accidental stubs: `catalog`, `cicd`, `quality`, `sources`, `transforms` → `/projects` (moved to per-project Workbench); `ai-employees` → `/agents`; `automations` → `/home` (**genuinely nothing was ever built behind this one**); `billing` → `/team?tab=billing`; `audit`, `governance` → `/settings?tab=audit-log`; `analytics` → `/home` (a working 8-endpoint backend exists, but this route itself renders no UI — Dashboard consumes 3 of the 8 endpoints instead).

**Real, substantive pages** (with line counts): `agents` (88), `agents/[id]` (243), `approvals` (209), `chat` (409), `dashboard` (178), `home` (101), `incidents` (223), `pipelines` (266), `projects` (254), `scheduled` (181), `settings` (705, 7 tabs), `tasks` (89), `tasks/[id]` (446), `team` (350 — contains one honest labeled "Coming soon — Stripe billing isn't wired up yet" string), plus a full `projects/[id]/*` tree (page, agents, chat, tasks, and a `workbench/` with catalog/cicd/contracts/incidents/lineage/pipelines/quality/sources/transforms tabs). Auth/onboarding (`login`, `signup`, `onboarding`, `invite/accept`, Google OAuth callback) are all real and multi-endpoint-wired.

**Dead component**: `components/shell/StubPage.tsx` — defined, exported, zero live usages; every reference to it in the current code is a historical comment ("was a StubPage, replaced by...").

### Component directories
`agents` (1 file — hire flow), `auth` (2 — login/signup chrome), `brand` (4 — theme-aware SVGs), `chat` (8 — MessageThread/SessionList/ContextPanel/ToolCallBlock, shared between direct chat and project chat), `dashboard` (7 — real, data-driven KPI/chart cards), `shared` (2), `shell` (10 — Sidebar/Topbar/CommandPalette/NotificationsPanel/RetiredRouteRedirect/ScopeBanner/ThemeToggle + dead StubPage), `tasks` (3), `ui` (12 — design-system primitives, hand-written CSS per CLAUDE.md), `workbench` (2 — real empty-state components).

### Confirmed gaps
1. `/api/v1/runs` has **zero frontend consumers** and zero backend test coverage — orphaned on both sides.
2. `/api/v1/analytics` exposes 8 endpoints; the frontend calls only 3 (overview, quality, recent-runs, all from Dashboard) — `pipelines`, `kpis` (GET+POST), `usage` have no caller, matching the code's own tracked-gap comments.
3. Self-serve billing is deliberately dead on both sides — `lib/api.ts` comments confirm `getPlans()`/`changePlan()` were removed because the backend always 501s.

The codebase is unusually self-documenting about its own retirements — most files that look like stubs at a glance turn out to be dated, reasoned redirects, not abandoned work.

---

## 10. GAPS

### Documented but not in code

| Doc claim | Reality |
|---|---|
| `USER_MANUAL.md` Screens 8/9/14/15/16/18/19/20/23 (Sources, Catalog, Governance, Automations, CI/CD, Analytics, Audit Logs, AI Employees, Billing) described as live top-level sidebar screens with specific forms/modals | All now a one-line `RetiredRouteRedirect` — none of the documented interactive elements render |
| `docs/DEMO_STEPS.md` Beat 9 — click "Governance" in the sidebar | No Governance item exists in the sidebar rail anymore; the route redirects |
| `README.md` — `frontend/ # (Coming soon)` | False — a ~24-route, fully built app exists |
| `README.md` — API table lists only 8 endpoints | Badly stale; 23 router files with well over 100 endpoints actually exist |
| `README.md` — "Running Tests… Expected: 10 passed" | 634 test functions across 85 files today |
| `USER_MANUAL.md` Screen 21 (Chat) — describes session list / thread / single-source context panel only | Current chat page also has channels, multi-agent membership, and task creation, undocumented |
| `docs/PRODUCT_STATUS.md` — "approving a blocked action doesn't execute it" | Already fixed and already documented as fixed in a sibling doc (`PRODUCT_AUDIT.md`) that this doc was never reconciled against |
| `docs/context/GOTCHAS.md` — "`RISK_ACTIONS['high']` names 4 tools that don't exist" | Current code: `RISK_ACTIONS = {"high": [], ...}` — an empty list, not phantom names; the specific claim is stale |

### In code but not documented

`api/v1/{projects,agents,tasks,channels,runs,uploads}.py` (six whole route modules); the entire Task/TaskStep plan→approve→execute lifecycle in `modules/orchestration/task_planner.py`/`task_executor.py` (only referenced in passing in root CLAUDE.md); `services/agent_scope.py`; the "Home → Projects → hire an Agent → Workbench/Tasks" frontend paradigm (8 routes); `components/workbench/` and `components/agents/`; `services/channel_routing.py`/`mentions.py`; `services/task_lock.py`/`source_lock.py`/`model_liveness.py`; `ScheduledAgentTask` and its `/scheduled` route.

### TODO/FIXME/HACK/XXX

**Zero hits** anywhere in backend or frontend source (grepped all `.py`/`.ts`/`.tsx` files).

### Hardcoded credentials/secrets

Both `.env` files are gitignored, not committed. Found in `dataops-agent/.env` (duplicated verbatim in `backend/.env`):

| File:line | Value | Assessment |
|---|---|---|
| `.env:3` | `APP_SECRET_KEY=[REDACTED]` | weak dev value, not committed |
| `.env:9` | `POSTGRES_PASSWORD=changeme` | placeholder |
| `.env:18` | `GEMINI_API_KEY=[REDACTED]` | real-looking live key, not committed |
| `.env:19` | `GROQ_API_KEY=[REDACTED]` | real-looking live key, not committed |
| `.env:25` | `JWT_SECRET=[REDACTED]` | weak dev value, signs auth tokens, not committed |
| `.env:33` | `SMTP_PASSWORD=your-smtp-password` | placeholder |
| `.env:34` | `SLACK_BOT_TOKEN=xoxb-your-slack-token` | placeholder |
| `.env:43-44` | `GOOGLE_OAUTH_CLIENT_ID`/`_SECRET` | real-looking live values, not committed |
| `.env:46` | `RESEND_API_KEY=[REDACTED]` | real-looking live key, not committed |
| `backend/config.py:9,21` | `APP_SECRET_KEY: str = "dev-secret"`, `JWT_SECRET: str = "dev-jwt-secret"` | committed, but obvious placeholders |
| `docker-compose.yml:32` | `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}` | committed, placeholder default only |
| `scripts/demo_reset.mjs:36-37` | `EMAIL = "demo@axiom-yc.ai"; PASSWORD = "AxiomDemo2026!"` | **committed to git**, a real (if throwaway demo-tenant) plaintext password |
| `backend/.env.example` | all placeholders | correctly clean, committed |

No other suspicious secret-like literal was found in `.py`/`.ts`/`.tsx` source.

---

## Bottom line

This is a large, genuinely working system, not a prototype — 23 backend routers, 35 real DB models, a compiled LangGraph agent with 40 real tools, a Celery pipeline with actual intermediate progress tracking, and a ~24-route Next.js frontend wired to nearly all of it. The half-built pieces are narrow and mostly self-labeled: Stripe billing (three honest, tested 501s), two Phase-3 Celery placeholders (`run_anomaly_detection`, `generate_daily_reports`), one orphaned route (`/runs`), two pieces of confirmed dead code (`approval_executor.py`, `csv_connector.py`), and a documentation set (README/USER_MANUAL/PRODUCT_STATUS/DEMO_STEPS) that is meaningfully behind a large September 2026 frontend rebuild that retired roughly a third of the screens those docs still describe as live. The one bug this report was asked to confirm — a 500 on `GET /api/v1/approvals/` — could not be reproduced against current code or current data after direct live testing; the most defensible finding is a test-coverage gap on that endpoint's success path, not a located defect.
