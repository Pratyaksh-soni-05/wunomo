# WUNOMO AI — MASTER CONTEXT & CONTINUITY BRIEF

**Purpose of this file:** This is the single handoff document for continuing Wunomo AI work in a new
Claude account. Upload it as the first project file in the new project. It reconstructs *what the
project is, what has been built, what state it is in, and what the open threads are* — the context
that lived in chat history and cannot be transferred between accounts.

**Assembled:** August 2026, from the twelve project knowledge files of the original project.
**Ventures covered:** Wunomo AI (product) · Alpha Parallel LLP (entity) — Pratyaksh Soni & Daksh Gupta, co-founders.

---

## 0. HOW TO USE THIS FILE

When starting a fresh chat in the new account, this document plus the re-uploaded source files
gives Claude everything it had before. The source PDFs are the detailed reference; this file is
the map and the state snapshot. If a detail here conflicts with a source PDF, the source PDF wins.

---

## 1. WHAT WUNOMO AI IS

Wunomo AI is an AI-native, multi-personality business operations platform. Rather than one generic
assistant, it is structured as an ecosystem of purpose-built "personalities," each acting as a digital
operator for a specific operational domain. The strategic bet: one successful personality becomes the
blueprint for many.

| Item | Value |
|---|---|
| Product | Wunomo AI |
| Type | AI-native multi-personality business operations platform |
| First personality built | **DataOps Agent** |
| Vision | Domain-specific AI personalities that operate business systems through natural language, governed execution, and modular backend services |
| Core value prop | Replace fragmented operational tooling with intelligent, secure, explainable, workflow-aware AI systems |
| Backend status | First personality complete as a production-grade foundation |
| Conversational agent name | **AXIOM** |

**Planned personality roadmap (15):** DataOps Agent (built) · Analytics Agent · BI Agent · Data Quality
Agent · Governance Agent · Incident Response Agent · ETL/Pipeline Engineer Agent · Knowledge Ops Agent ·
RevOps Agent · Finance Ops Agent · Support Ops Agent · Compliance Agent · Growth Agent · Founder Copilot ·
Custom Enterprise Personalities.

---

## 2. TECHNICAL STATE — THE DATAOPS AGENT BACKEND

### 2.1 Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI |
| Agent layer | LangGraph + LangChain |
| Primary database | PostgreSQL 16 |
| ORM / DB access | SQLAlchemy async + asyncpg |
| Cache / queue | Redis |
| Async jobs | Celery (worker + beat) |
| LLM layer | **Gemini (`gemini-3.5-flash`) primary**, Groq (`llama-3.3-70b-versatile`) fallback — corrected 2026-08-12; this was previously documented backwards |
| Frontend | Next.js 15 App Router, Zustand, ported design-system CSS (not Tailwind), JWT in localStorage — built out across many phases since this file was first assembled; no longer "the next major build," see §5 |
| Auth | JWT (python-jose), bcrypt, passlib |
| Testing | pytest + pytest-asyncio (backend only — no frontend test framework exists yet) |
| Logging | structlog |
| Container runtime | Docker Compose |

**Local project path:** `C:\Pratyaksh Personal\My Projects\ai workforce\dataops-agent` (this file previously listed a stale path from a different machine — corrected 2026-08-12)
**Services & ports:** Backend API `8000` · Frontend `3000` (run manually via `npm run dev`, not a Docker service) · PostgreSQL `5432` · Redis `6379` · Celery worker (internal) · Celery beat (internal)

### 2.2 API segments (all under `/api/v1/`)

**This list is stale as of 2026-08-12 — it predates several major features and is kept here only for
the original 13, unedited, for history.** The authoritative, currently-accurate list lives in
`CLAUDE.md`'s Architecture Summary and Status Table — read that instead of trusting the count below.
At minimum, everything built since this list was written and NOT reflected in it: **Onboarding**
(profile capture), **Team** (invites, roles, member management), **Settings** (workspace config,
notifications, AI model override, theme, API keys), **Billing** (plan/quota, usage), **API Keys**
(CRUD only — not yet usable as a request credential), and **Tasks** (item 6 — long-running,
multi-step AXIOM-planned work with human review/approval/execution, a 7-stage feature completed
2026-08-12).

The original 13, as first documented:

1. **Auth** — register, login, me. JWT + multi-tenancy. Every other segment is gated behind it.
2. **Uploads** — upload CSV/Excel/JSON files, register them as data sources.
3. **Sources** — CRUD for data connections; profiling, schema drift detection, metadata sync.
4. **Pipelines** — pipeline definitions and orchestration.
5. **Runs** — pipeline run history and status.
6. **Quality** — quality rules, validation, trust scoring.
7. **Incidents** — detect, create, triage, resolve operational failures.
8. **Governance** — lineage, audit trail, data contracts, policy.
9. **Approvals** — human-in-the-loop approval workflows for gated actions.
10. **Analytics** — platform health score, metrics dashboards.
11. **Transformations** — SQL/pandas generation and sandboxed execution.
12. **CI/CD** — the automated safety layer (see 2.4).
13. **Chat (AXIOM)** — LangGraph agent with tool access + personality modes; session history.

### 2.3 Daily operator journey (the demo narrative)

Login → check sources health → run drift detection → review overnight run history → investigate
failures as incidents → run quality checks → ask AXIOM for a natural-language summary → clear pending
approvals → review CI/CD deployments → check the analytics health score. All through one authenticated
REST API, fully audited and AI-assisted.

### 2.4 CI/CD feature — architecture

Treats a *pipeline definition* (SQL transformations, quality rules, schema expectations, scheduling) as
the deployable artifact. On a GitHub push webhook:

```
GitHub push → FastAPI (api/v1/cicd.py) → Celery worker (services/cicd_tasks.py)
  ├── Schema check      (models/schema_snapshot.py)
  ├── Quality dry run   (models/quality.py)
  ├── SQL static analysis (pure Python)
  └── History check     (models/pipeline.py → PipelineRun)
        ↓  risk score 0–100
   Gate: score < 60 → auto-deploy | score ≥ 60 → ApprovalRequest
        ↓
   Deploy (services/cicd_deployment.py)
        ↓
   Celery Beat every 60s (services/cicd_monitor.py)
   ├── 3 runs pass → healthy
   └── 2+ runs fail → auto rollback → CICDIncident + Slack notify (services/cicd_notify.py)
```

**New tables:** `PipelineCommit` (commit_sha, branch, author, changed_files, ci_status, gate_decision,
risk_score, check_results) and `PipelineDeployment` (commit_sha, status, rollback_commit_sha,
monitoring_active, post_deploy_run_count, post_deploy_failure_count). Files: `models/cicd.py`, `schemas/cicd.py`.
No new infrastructure was introduced — everything reuses the existing stack.

### 2.5 Hard-won fixes (do not regress these)

**Re-verified against the actual current code on 2026-08-12** — two of these four are less settled
than this section previously claimed. Don't trust this table without re-checking again next time
something in this area changes; see the note on each row.

| # | File | Problem | Fix | Current status (2026-08-12) |
|---|---|---|---|---|
| 1 | `postgres_connector.py` | Endpoints each built their own DB connection → "no PostgreSQL user name specified" | Centralised all Postgres connections through one connector reading `connection_config` from the Source record | **Partially regressed.** `postgres_connector.py` is real and is used correctly by the sync path. But `modules/ingestion/schema_profiler.py`, `modules/transformation/python_runner.py`, and `modules/transformation/sql_runner.py` each independently call `asyncpg.connect()` with their own hand-built DSN, not through it. Real, current duplication — not fixed this session (out of scope), just documented. |
| 2 | `services/llm_service.py` | `get_primary_llm()` always returned `ChatGoogleGenerativeAI`, so Groq/Llama models 404'd on the Gemini API | Route by model name — if it contains `llama`/`mixtral`/`gemma`, return `ChatGroq` | **Holds.** A shared `_build_llm()` (used by both `get_primary_llm()` and `get_fallback_llm()`) does exactly this branch today. |
| 3 | `api/v1/chat.py` (~line 63) | `datetime.now(timezone.utc)` is timezone-aware; the column is `TIMESTAMP WITHOUT TIME ZONE` → DataError on every chat save | Use `datetime.utcnow()` (timezone-naive) | **Holds**, and checked far beyond just `chat.py`: every other file that writes a timestamp either uses the naive form directly or the safe `datetime.now(timezone.utc).replace(tzinfo=None)` pattern. One deliberate, correct exception: the CI/CD tables (`models/cicd.py`) use genuinely timezone-aware `DateTime(timezone=True)` columns on purpose, so `datetime.now(timezone.utc)` used directly there is correct, not a bug — don't "fix" it if you see it. |
| 4 | Docker env loading | Editing `.env` and restarting didn't pick up new keys — old values stayed cached | Always `docker compose down && docker compose up -d`; verify with `docker compose exec backend printenv` | **Superseded by a more precise fix, documented in `CLAUDE.md`'s Gotchas**: `docker compose restart <service>` never reloads `.env`; `docker compose up -d --force-recreate <service>` does, without the full-stack disruption of `down && up`. Prefer that. |

**The "never localhost" gotcha is not just a gotcha — it's a live, active bug today, not just a risk:**
`modules/transformation/python_runner.py` and `modules/transformation/sql_runner.py` both write
`config.get("host", "localhost")` — a silent fallback to `localhost` if a source's
`connection_config` is ever missing `host`. Inside Docker, `localhost` means the container itself,
not the `postgres` service — this would silently try (and fail) to reach a database that was never
where it looked. `postgres_connector.py` and `schema_profiler.py` do this correctly (`cfg['host']`,
no default — fails loudly instead of silently going to the wrong host). Not fixed this session
(out of scope, logged for whoever picks it up) — see `docs/context/SESSION_LOG.md`'s 2026-08-12 entry.

**One more recurring gotcha, not re-verified this pass:** the Groq free tier's 12,000 TPM limit was
hit by an oversized system prompt; the workaround at the time was moving to `llama-3.1-8b-instant`.
`CLAUDE.md`'s own Gotchas describe a later, different Groq constraint (a shared org-level TPD budget,
not a per-request TPM one) — these may be the same underlying limit observed at two different times,
or two different limits; not reconciled here.

### 2.6 Operating commands

```bash
cd dataops-agent
docker compose up -d --build          # start full stack
docker compose down                   # stop
docker compose down -v                # stop + wipe volumes (clean reset only)
docker compose up -d --force-recreate backend   # picks up a changed .env (restart does NOT)
docker compose logs -f backend        # or celery_worker / celery_beat
docker compose ps
docker compose exec backend python -m pytest tests/ -v --tb=short

cd frontend
npm run dev                            # frontend is NOT a Docker service — run it separately
```
Health: `http://localhost:8000/health` and `http://localhost:8000/health/db` · Frontend: `http://localhost:3000`

### 2.7 Environment variables (names only — see §6 on secrets)

`DATABASE_URL`, `SYNC_DATABASE_URL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_URL`,
`PRIMARY_LLM_PROVIDER`, `PRIMARY_LLM_MODEL`, `FALLBACK_LLM_MODEL`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
`JWT_SECRET`, `APP_ENV`.

---

## 3. BUSINESS & MARKET STATE

### 3.1 The problem

Data teams spend **40–60% of sprint capacity firefighting** instead of building. Pipelines break
silently and surface in exec dashboards after the damage. Root-cause work is scattered across Slack,
notebooks, cron logs, and tribal knowledge. A single pipeline failure costs a mid-size team 8–20
engineer-hours. Poor data quality costs the average enterprise roughly $12.9M/year (Gartner); over a
quarter of organisations lose $5M+ annually and 7% lose $25M+ (IBM, 2025).

### 3.2 Why now

Production-ready LLMs · 8–15 tool sprawl per mid-market data team driving consolidation demand ·
enterprise acceptance of agents as operational systems · 30–40% YoY data-engineering salary inflation
in India · RBI/SEBI compliance pressure · accelerating BigQuery/Snowflake adoption. 74% of enterprises
expect to use agentic AI within two years — but can't trust their data layer under it. **Wunomo sells
the governed data layer beneath the agent wave.**

### 3.3 Market sizing

| Metric | Value | Scope |
|---|---|---|
| TAM (global, 2025) | ~$6.5B | AI DataOps + AI workforce convergence |
| TAM (global, 2028) | ~$28B | at ~45% CAGR |
| TAM (India, 2025) | ~$420M (~₹3,500Cr) | → ~$2.1B by 2028 |
| SAM (India) | ~₹195 crore/yr (~$23M) | ICP-matched orgs with tooling budget |
| SAM (global, Yr 3) | ~₹467 crore | India + SEA + UAE + US SME |
| SOM Year 1 (2026) | ₹90L–1.3Cr | 50–70 customers, founder-led India sales |
| SOM Year 2 (2027) | ₹5–7.5Cr | 200–300 customers |
| SOM Year 3 (2028) | ₹22–32Cr | 700–1,000 customers, ~14% of India SAM |

Category validation: ~$2.9B VC across 38 data-observability companies, 4 unicorns, M&A up to Cisco/Splunk
($28B) and Snowflake's 2026 Observe acquisition.

### 3.4 ICP

50–500 employees (primary), 500–2,000 (secondary) · ₹10–150 crore revenue (India) or $5M–$50M global ·
Series A–C or profitable SMEs · 1–10 person data teams · cloud-first on Postgres/MySQL/BigQuery/Snowflake ·
Phase-1 geographies Bangalore, Mumbai, Pune, NCR, plus Singapore and UAE.

**Verticals:** (1) B2B SaaS & tech — pipeline failures hitting product metrics, urgency before Series B/C
diligence. (2) E-commerce & D2C — cross-source inconsistency, manual reconciliation, freshness SLA breaches.
(3) Financial services & fintech — lineage and audit for RBI/SEBI, highest willingness to pay.

**Buyers:** economic buyer = CTO / VP Eng / Head of Data (budget sign-off); champion = data engineer / analytics engineer.

### 3.5 Competitive position

| Competitor | Their weakness | Wunomo's angle |
|---|---|---|
| **UiPath** | Rule-based and brittle; 3–6 month deployments with SI dependency; ₹20L+ enterprise minimum; no DataOps-native orchestration | 2–4 week deployment; LLM-native reasoning; purpose-built for pipelines/quality/lineage; ₹5k–2L/month entry |
| **Microsoft Copilot** | Full value only if already all-in on M365; $30/user/mo on top of E3/E5 | Stack-agnostic, DataOps-specific depth |
| **Glean** | Enterprise-only, no self-serve, ~6-month sales cycle, $100k–500k+ ARR | Self-serve mid-market entry |
| **Ema.ai** | US-focused, no India pricing, $50k–300k+ ARR | India-first GTM and pricing |
| **Monte Carlo** | Observability only — no pipeline or transformation execution | Full operating layer, not just alerts |

**The pricing gap thesis:** nothing purpose-built serves the ₹5k–15k/month India mid-market bracket
between free tools and enterprise contracts. That gap is the wedge.

### 3.6 Pricing model (proposed, 3 tiers)

- **Tier 1 — Operator (Starter):** ₹4,999/mo or ₹49,999/yr. 3 sources, 5 pipelines, 500 runs/mo, 20 quality
  rules, 50 SQL generations/mo, Engineer + Analyst chat personas, 30-day retention, shared infra.
- **Tier 2 — Navigator (Professional):** ₹14,999/mo or ₹1,49,999/yr. Unlimited sources, 30 pipelines,
  5,000 runs/mo, unlimited quality rules and transformations with sandboxed execution, lineage graph to
  100 nodes, 10 pending approvals, data contracts.
- **Tier 3 — Enterprise:** custom. (See `06_Pricing_Research_Validation` for the full tier-3 spec, the
  willingness-to-pay validation script, and the pricing assumption log.)

### 3.7 Customer discovery

A 10-question, 30–45 minute interview script exists (co-founder-led, no selling), plus a single-interview
documentation template and a cross-interview synthesis template for spotting patterns across 10+
conversations. Question arc: team structure → current stack → last real failure → root-cause workflow →
trust in dashboards → compliance pressure → maintenance vs. build ratio → ideal 12-month state → (Q9–Q10
in the source doc).

### 3.8 Investment brief structure

`Wunomo_Market_and_Investment_Brief.pdf` (v2.0, July 2026, 23 pages, board/investor audience) is organised as:
Part I — market & customer opportunity; Part II — independent risk assessment (risk register; Risk 1 is
security/agent-as-exfiltration-vector, Risk 2 is buyer-can-build-it-themselves, Risks 3–8 summarised);
Part III — a capital-efficient, security-first path to first revenue that de-risks the beta before touching
any customer data.

---

## 4. FILE INDEX — RE-UPLOAD ALL OF THESE

| # | File | What it holds |
|---|---|---|
| 1 | `wunomo_full_review_main.pdf` | **The core technical reference.** All 13 segments, every endpoint, dry-run walkthroughs, the 4 custom fixes, full `.env` reference |
| 2 | `Wunomo_AI_Backend_Documentation_Organized.pdf` | Product-level A-to-Z: vision, 15-personality roadmap, business value |
| 3 | `Wunomo_AI_Backend_Startup_Guide.pdf` | Operational handbook: prerequisites, env setup, Docker commands, test commands, validation workflow |
| 4 | `Wunomo_CICD_Complete_Documentation.pdf` | CI/CD architecture, phased build, risk scoring, frontend integration mappings, SaaS readiness, gaps |
| 5 | `Wunomo_Market_and_Investment_Brief.pdf` | Board/investor brief v2.0 — market, risk register, path to revenue |
| 6 | `01_Competitive_Analysis.pdf` | UiPath, Microsoft Copilot, Glean, Ema.ai — pricing, gaps, differentiation |
| 7 | `02_Ideal_Customer_Profile.pdf` | Company profile, 3 verticals, decision-maker personas, triggers |
| 8 | `03_TAM_SAM_SOM.pdf` | Market sizing methodology and 3-year SOM build |
| 9 | `04_Customer_Discovery_Framework.pdf` | Interview script + documentation + synthesis templates |
| 10 | `05_Problem_Solution_Fit.pdf` | Pain, cost quantification, why-now, solution one-pager |
| 11 | `06_Pricing_Research_Validation.pdf` | Competitor benchmark, 3-tier model, WTP script, assumption log |
| 12 | `__REGISTRATION_IS_100__WORKING_.pdf` | Auth debugging session notes — **contains live credentials, see §6** |

---

## 5. OPEN THREADS — WHERE WORK LEFT OFF

Carry these forward into the new account. Update as you go.

**Last reconciled against actual repo state: 2026-08-12.** The Engineering list below was rewritten
that day after checking each item against the real code rather than carried forward unread — the
Business list was **not** re-verified (out of scope for that session; nothing in the repo can confirm
or deny it) and may itself be stale.

**Engineering**
- [x] ~~Frontend integration — the frontend itself is the next major build~~ **Done, extensively.**
  This was true when first written; it no longer is. The frontend has been built out across many
  phases since — full screens for every backend segment plus Team/Settings/Billing/API Keys/Tasks,
  both light and dark themes, live-verified via Playwright each phase. See `CLAUDE.md`'s Status Table
  for the phase-by-phase build record — don't re-plan this from scratch.
- [x] ~~Item 6 (long-running AXIOM tasks)~~ **Done, all 7 stages, closed 2026-08-12.** Wasn't on this
  list because it didn't exist when the list was written — the biggest single feature built since this
  file was assembled. A goal typed in chat becomes a real, human-reviewable, editable, approvable
  multi-step plan that AXIOM then executes with a fresh per-step permission re-check, mid-task
  approval gates for risky actions, and real termination caps (step/wall-clock/credit budgets, loop
  detection). Full detail in `CLAUDE.md`.
- [ ] **Real, live gap found 2026-08-12, not fixed (see `docs/context/SESSION_LOG.md` for detail):**
  `python_runner.py` and `sql_runner.py` silently default a missing source `host` to `localhost`
  instead of failing loudly — the exact failure mode the "never localhost" gotcha (§2.5) exists to
  prevent, currently only half-guarded against.
- [ ] **Related, same discovery:** `postgres_connector.py` is not actually the sole path for building
  Postgres connections — three other files (`schema_profiler.py`, `python_runner.py`, `sql_runner.py`)
  independently reimplement the same DSN-building logic. Worth consolidating, not urgent by itself,
  but it's *why* the localhost-default bug above could exist in two places at once instead of one.
- [ ] **Credential rotation flagged in §6 below has still not happened** — checked directly 2026-08-12,
  not assumed: `dataops-agent/.env` and `dataops-agent/backend/.env` both still have `POSTGRES_PASSWORD`
  set to the literal default `changeme`, and `JWT_SECRET` is only 9 characters (still reads as a
  placeholder, not a real rotated secret). Dev-only, nothing deployed, but genuinely still open.
- [ ] CI/CD "what is not yet built" gaps — not re-verified 2026-08-12; carried forward unread from the
  original assembly. Re-check before trusting.
- [ ] SaaS readiness / production deployment — still a documented plan, not yet executed. `CLAUDE.md`
  now has much more detail on this specifically (a "public-launch risk cluster" with 5 tracked items:
  flipping to paid LLM keys, a real billing free-upgrade hole now closed, the domain `wunomo.in` already
  purchased but not yet configured, nightly backups not yet set up, and a Cloudflare R2 file-storage
  migration confirmed not launch-blocking) — read that section instead of re-deriving this from scratch.
- [ ] Groq free-tier ceiling is still a live constraint, but the shape of it is now better understood —
  `CLAUDE.md`'s Gotchas describe it as a shared, org-level daily token budget (not a per-request TPM
  cap as originally documented here), observed being exhausted mid-session more than once. Deciding on
  a paid tier is still open.
- [ ] Personalities 2+ (Analytics Agent is the natural second) — still nothing built. Still true.
- [ ] **New, from this session's checkpoint itself:** 14 commits (the entire Item 6 feature) exist only
  on this machine — not yet pushed to `origin/master`. Nothing is actually durable against a lost
  machine until that push happens.
- [ ] **New, from this session's checkpoint itself:** `.claude/commands/MASTER_CATCHUP_PROMPT.md` is
  stale (wrong local path, pre-Tasks-feature architecture, wrong LLM provider priority) — known,
  deliberately not rewritten this session per the user's own call; still needs doing.

**Business** *(not re-verified 2026-08-12 — carried forward as-is)*
- [ ] Customer discovery interviews — framework exists; run 10+ and fill the synthesis template.
- [ ] Pricing validation — the assumption log is empty until WTP conversations happen.
- [ ] Investment brief Part III (security-first beta plan) — execute the de-risking sequence before touching customer data.

---

## 6. SECURITY — ACT ON THIS BEFORE RE-UPLOADING

**Status check, 2026-08-12: none of this has been done yet.** Checked directly, not assumed —
`POSTGRES_PASSWORD` is still the literal default `changeme` in both real `.env` files, and
`JWT_SECRET` is only 9 characters (still reads as a placeholder). This is dev-only — nothing here is
deployed — but it's genuinely still open, not resolved. Also relevant: the one source file this
section names as containing a live JWT/password (`__REGISTRATION_IS_100__WORKING_.pdf`) was checked
2026-08-12 and **does not exist anywhere in this repo** — only 2 of the 12 original source PDFs are
present (`Document/Wunomo_AI_Backend_Documentation_Organized.pdf` and
`Document/Wunomo_AI_Backend_Startup_Guide.pdf`, both already tracked in git and not spot-checked for
embedded secrets this session — see `docs/context/SESSION_LOG.md`'s Gotchas). Nothing found in git
history itself contains a real key so far, but that's a "not found," not a certified "confirmed clean."

The original project files contain **real, live-looking secrets**. Before or immediately after
re-uploading, rotate them:

- A **real account password** and personal email appear in the registration walkthrough doc.
- A **live JWT access token**, plus real `tenant_id` and `user_id` UUIDs.
- Database credentials (`dataops_user` / `changeme`) — a default that must not survive into production.
- Placeholders for `GROQ_API_KEY` and `GEMINI_API_KEY` — verify the real ones were never committed to git.

**Action:** change that account password, rotate `JWT_SECRET` (invalidating old tokens), replace the
Postgres password, and confirm no `.env` with real keys is in version history. Doing this at a migration
boundary is the cheapest time to do it.

---

## 7. WHAT COULD NOT BE CARRIED OVER

Be honest with yourself about the gap, and re-establish it deliberately in the first few chats:

- Conversation history across the old account's chats — not transferable between personal accounts.
- Any decisions, rejected approaches, or reasoning that lived only in chat and never made it into a file.
- Claude's memory of the old account.

**Not lost:** everything in `C:\Personal Projects\workforce-agent`, including `CLAUDE.md`, `.claude/`,
the git history, and all source code. Claude Code reads those from disk, so re-authenticating is all
that's needed there.
