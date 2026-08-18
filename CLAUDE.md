# CLAUDE.md — AXIOM DataOps Agent

**What this is:** AXIOM is an autonomous AI DataOps agent — it connects to a company's data
sources, watches pipelines, runs quality checks, investigates incidents, and now (as of
2026-08) plans and executes real multi-step tasks, all through a chat interface with
human approval gates on anything risky. It's the first of a planned family of AI "personality"
products under the Wunomo AI brand (see `docs/context/WUNOMO_MASTER_CONTEXT.md` for the
product/business framing — this file is engineering-only). The one real application in this
repo is `dataops-agent/`; nearly everything else at repo root is reference material, not
app code (see Repo Layout below).

**Read `docs/context/` before assuming this file has the full picture** — it doesn't anymore,
by design. See "Deeper History" at the bottom.

---

## Stack

- **Backend:** FastAPI (async, Python 3.11/3.13), SQLAlchemy 2.0 async + asyncpg, PostgreSQL 16,
  Redis, Celery (worker + beat), LangGraph/LangChain v1.x agent graph.
- **LLM:** Gemini (`gemini-3.5-flash`) primary, Groq (`llama-3.3-70b-versatile`) fallback.
  Both have real daily quota ceilings that get hit in normal use — see Hard Rule 2 and
  `docs/context/GOTCHAS.md`.
- **Frontend:** Next.js 15 App Router, React 19, Zustand, hand-written CSS design system
  (not Tailwind), JWT in `localStorage`. Runs via `npm run dev` in its own terminal — it is
  **not** a Docker service (commented out in `docker-compose.yml`).
  Frontend visual work: see `design/CLAUDE_CODE_BRIEF_full_frontend.md`. Palette, button
  tiers, and motion rules are specified there — do not improvise colours or add animation
  libraries.
- **Auth/tenancy:** JWT-based, multi-tenant **by convention, not enforcement** — every query
  against tenant-owned data must manually filter `WHERE tenant_id = ...`; nothing in the
  framework does this for you. Treat "did this query get tenant-scoped?" as a mandatory
  review question on every new query.

## Repo layout

```
dataops-agent/
├── backend/           the FastAPI app — api/, agent/, models/, modules/, services/, migrations/, tests/
├── frontend/           the Next.js app, src/-scoped except public/ and design/:
│     ├── src/app/          root layout, icons, login/, signup/, onboarding/, invite/, api/,
│     │                     and the (app)/ route group holding all authenticated screens
│     ├── src/components/   auth, brand, chat, dashboard, shared, shell, tasks, ui
│     ├── public/           frontend root, not inside src/
│     └── design/           frontend root; committed, never imported, never bundled
├── docker-compose.yml   backend + postgres + redis + celery_worker + celery_beat (frontend is NOT here)
├── .env                  the real env file Docker actually reads (see Run & test commands below)
└── backend/.env          a SECOND, slightly-drifted copy — Docker does not read this one
docs/
├── context/              engineering + product history that survives an account migration — read this first
├── SELF_TEST_GUIDE.md    beginner click-by-click product walkthrough
├── PRODUCT_AUDIT.md, PRODUCT_STATUS.md    deeper product-side references
```
Everything else at repo root (`Document/*.pdf`, `generate_dataops_project.py`, sample CSVs,
`marketing-site/`) is scaffolding, sample data, or a separate product living on its own git
branch — not part of this app, don't touch it as a side effect of other work.

## Run & test commands

```bash
cd dataops-agent
docker compose up -d --build              # start backend + postgres + redis + celery
docker compose ps                          # confirm all 5 containers say "Up"
curl http://localhost:8000/health          # {"status":"ok",...}
curl http://localhost:8000/health/db       # {"status":"ok","db":"connected"}

docker compose up -d --force-recreate backend    # after editing .env — `restart` does NOT reload it
docker compose exec backend python -m pytest tests/ -v --tb=short

cd frontend
npm run dev                                # separate terminal, not a Docker service
npx tsc --noEmit                           # type-check before any frontend commit
npm run build                              # production build — also catches ESLint errors dev mode misses
```

## Code conventions actually used here (not aspirational)

- **One Celery beat entry per recurring job**, defined statically in `services/celery_app.py` —
  don't try to register per-pipeline dynamic schedules at runtime; that pattern exists in the
  code (`modules/orchestration/scheduler.py`) but is dead — it can't work across the
  `backend`/`celery_beat` process boundary. The real scheduling mechanism polls the DB every
  60s (`services/tasks.py:check_scheduled_pipelines()`).
- **Every enum in `models/all_models.py` is `UPPERCASE_MEMBER = "lowercase_value"`.**
  `models/cicd.py`'s enums are the opposite (lowercase members) — don't pattern-match one
  onto the other.
- **A new Alembic migration for a `SAEnum`-backed column must use the Python member names
  (uppercase), never the `.value` strings** — SQLAlchemy stores the member name by default,
  and `compare_metadata()` won't catch it if you get this wrong.
- **Tool functions exposed to the AXIOM agent must accept `tenant_id`/`user_id`/`session_id`
  as declared args, but never trust the LLM's values for them** — `agent_node` force-overwrites
  these server-side on every outgoing tool call. Extend that override loop for any new tool
  that needs them; never rely on the LLM supplying them correctly.
- **No agent tool calls back into this app's own REST API over HTTP.** Every tool calls the
  same service-layer function (`modules/*`, `services/*.py`) the REST endpoint itself calls,
  in-process.
- **One fix or feature per commit**, with the reasoning in the message body, not just the diff.

## Hard rules — do not regress these

These four were each debugged live, from real production-shaped failures. Re-verified against
the actual code on 2026-08-12 — status noted per rule; see `docs/context/WUNOMO_MASTER_CONTEXT.md`
§2.5 for the full verification detail.

1. **Do not build Postgres connections outside `postgres_connector.py`.**
   *Known current exception, not yet fixed:* `modules/ingestion/schema_profiler.py`,
   `modules/transformation/python_runner.py`, and `modules/transformation/sql_runner.py` each
   independently build their own connection today. Don't add a fourth — and if you're touching
   any of those three anyway, consolidating onto `PostgresConnector` closes a real gap.

2. **`get_primary_llm()` (and `get_fallback_llm()`) must never return `ChatGoogleGenerativeAI`
   unconditionally** — both route through `_build_llm()` in `services/llm_service.py`, which
   branches on the model name: contains `llama`/`mixtral`/`gemma` → `ChatGroq`, else →
   `ChatGoogleGenerativeAI`. This still holds as of 2026-08-12. If you ever see a hardcoded
   `ChatGoogleGenerativeAI(...)` construction outside `_build_llm()`, that's a regression.

3. **Never write a timezone-aware `datetime.now(timezone.utc)` into a naive
   `TIMESTAMP WITHOUT TIME ZONE` column** — use `datetime.utcnow()`, or
   `datetime.now(timezone.utc).replace(tzinfo=None)` (both patterns are already used
   throughout the codebase; either is fine). **Exception, not a bug:** `models/cicd.py`'s
   tables (`PipelineCommit`, `PipelineDeployment`, `CICDIncident`) deliberately use
   `DateTime(timezone=True)` columns — a genuinely timezone-aware value there is correct,
   don't "fix" it.

4. **Never default a source's `host` to `"localhost"`.** Inside Docker, `localhost` means
   the container itself, not the `postgres` service — a source's real Postgres host is always
   the literal string `"postgres"` (the Docker service name), read from `connection_config`,
   never assumed. *Known current violation, not yet fixed:* `python_runner.py` and
   `sql_runner.py` both do `config.get("host", "localhost")` — a silent wrong-host fallback
   instead of failing loudly. `postgres_connector.py` and `schema_profiler.py` do this
   correctly (`cfg['host']`, no default).

## Deeper history — read `docs/context/` for anything this file doesn't cover

This file is deliberately lean — it's read at the start of every session, so density matters
more than completeness. The full history lives here, split by concern:

| File | Read it when you need... |
|---|---|
| `docs/context/WUNOMO_MASTER_CONTEXT.md` | The product/business framing, market state, and the full verification detail behind the 4 hard rules above. |
| `docs/context/SESSION_LOG.md` | What happened in each dated working session — newest first, includes decisions and why, not just what changed. |
| `docs/context/ENGINEERING_HISTORY.md` | The old CLAUDE.md's full banner/status narrative (pre-2026-08-12) — every phase, in the order it was built. Mostly superseded by `STATUS_TABLE.md` below, kept for the "why" behind old decisions. |
| `docs/context/STATUS_TABLE.md` | Exhaustive, phase-by-phase build record — what's done, how it was live-verified, exact test counts. The single most detailed file in this repo. |
| `docs/context/GOTCHAS.md` | Specific, hard-won "don't do X, here's why" notes beyond the 4 hard rules above — append-only, never trimmed. |
| `docs/context/WORKFLOW_RULES.md` | How a session is expected to operate on this repo (commit granularity, verification standard, when to propose before building). |

**Note on this split (2026-08-12):** the old `CLAUDE.md` was ~1,000 dense lines and grew that
way for good reason — this checkpoint session split it by concern rather than deleting
anything, so the depth is still here, just not loaded by default every session. If you're
about to touch code this file doesn't mention, check the Status Table and Gotchas files
before assuming something hasn't been tried.
