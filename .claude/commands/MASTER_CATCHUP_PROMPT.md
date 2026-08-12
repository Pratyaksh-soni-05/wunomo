# WUNOMO — MASTER CATCH-UP PROMPT

Two prompts. The first is for **Claude Code** (the CLI, reading your actual repo). The second is a
shorter one for a **claude.ai project chat**. They do different jobs — use both.

---

## STEP 0 — ONE-MINUTE PREREQUISITE

Claude Code can only read what's on disk. Put the migration context inside the repo so it can find it:

```powershell
cd "C:\Personal Projects\workforce-agent"
mkdir docs\context
# copy WUNOMO_MASTER_CONTEXT.md into docs\context\
# copy your chat handoff briefs into docs\context\ too
git add docs/context && git commit -m "docs: add migration context and handoff briefs"
```

Without this step, Claude Code has your code but not your *decisions*. With it, one prompt rebuilds
the whole picture.

---

## PROMPT 1 — CLAUDE CODE MASTER CATCH-UP

Open a fresh Claude Code session in `C:\Personal Projects\workforce-agent` and paste everything
between the lines.

---

You are picking up the Wunomo AI DataOps Agent codebase cold. I've migrated to a new Claude account,
so you have no memory of this project — but everything you need is on disk. Your job this session is
to **rebuild full context and report back**. Do not write or modify any code until I say so.

Work through these phases in order.

**Phase 1 — Read the context layer.**
Read `docs/context/WUNOMO_MASTER_CONTEXT.md` first — it is the authoritative state snapshot for both
the product and the business. Then read any other files in `docs/context/` (these are handoff briefs
from previous sessions). Then read `CLAUDE.md`, `README.md`, `.env.example`, `docker-compose.yml`,
and `requirements.txt`.

**Phase 2 — Map the codebase.**
Walk the repo structure and give me a tree of the meaningful directories (skip `venv`, `__pycache__`,
`node_modules`, `.git`). For each of the 13 API segments listed in the master context, confirm whether
the corresponding file exists under `app/api/v1/` and note anything present in the code that isn't in
the docs, or documented but missing from the code. That delta is the most valuable thing you can find.

**Phase 3 — Read the git history.**
Run `git log --oneline -40`, `git status`, and `git branch -a`. Tell me: what branch am I on, is
anything uncommitted or stashed, what were the last few things I was actually working on, and does the
commit history suggest any work left mid-stream.

**Phase 4 — Verify the four critical fixes are still intact.**
The master context documents four fixes that are easy to accidentally regress. Check each one in the
actual source and report PASS/FAIL with the file and line:
1. `postgres_connector.py` exists and is the single path for building Postgres connections — no endpoint
   builds its own connection string independently.
2. `services/llm_service.py` → `get_primary_llm()` routes by model name (returns `ChatGroq` when the
   model contains `llama`/`mixtral`/`gemma`, not always `ChatGoogleGenerativeAI`).
3. `api/v1/chat.py` uses timezone-naive `datetime.utcnow()`, not `datetime.now(timezone.utc)`. Also grep
   the whole codebase for `datetime.now(timezone.utc)` and flag every other place it appears against a
   `TIMESTAMP WITHOUT TIME ZONE` column.
4. Any source `connection_config` uses `host: "postgres"` (Docker service name), never `localhost`.

**Phase 5 — Assess the CI/CD feature.**
Read `app/api/v1/cicd.py`, `app/models/cicd.py`, `app/schemas/cicd.py`, and the `services/cicd_*.py`
files. Confirm the flow matches the documented architecture: webhook → 4 CI checks → risk score →
gate at 60 → deploy → 60-second monitor → auto-rollback on 2+ failures. List what's implemented,
what's stubbed, and what's missing.

**Phase 6 — Check the test suite.**
Read the `tests/` directory. Tell me what's covered and what obviously isn't. Do not run the tests yet —
Docker may not be up, and I want the report before anything executes.

**Phase 7 — Report.**
Write me a **State of the Build** report as a markdown file at `docs/context/STATE_OF_BUILD.md`:
- Current state in 5 sentences
- The four-fix verification table
- Segment-by-segment implementation status (built / partial / documented-only)
- Every delta you found between docs and code
- Anything that looks broken, half-finished, or risky
- The 5 highest-value next actions, ranked, each with a one-line reason

**Phase 8 — Refresh CLAUDE.md.**
Rewrite `CLAUDE.md` so that a future session in this repo gets oriented in a single read: stack, layout,
the four fixes stated as hard rules, the run/test commands, and the conventions you observed in the code
(not the ones you'd prefer). Keep it under 150 lines — it loads on every session, so it should be dense
and free of filler. Show me the diff before writing.

**Ground rules for this session:**
- Read-only until I approve changes. No refactors, no "while I was in there" edits.
- Never print, echo, or write real credentials, API keys, JWTs, or `.env` values into any file or into
  chat. Use placeholders.
- If something in the docs contradicts the code, the **code is the truth** — flag the doc as stale.
- If you're unsure whether something is intentional, ask rather than assume. I'd rather answer three
  questions than unpick a wrong assumption later.

Start with Phase 1.

---

## PROMPT 2 — CLAUDE.AI PROJECT KICKOFF

Paste this into the first chat of the rebuilt Wunomo project on the web, once all files are uploaded.
It verifies the migration and gets a working memory going.

---

This project has just been rebuilt in a new account after a migration, so this is our first
conversation — but the full context is in the project files.

Start by reading `WUNOMO_MASTER_CONTEXT.md`, then skim the other project files. Then answer these,
concisely, so I can confirm the context survived:

1. What is Wunomo AI, and what's the relationship between the DataOps Agent and the broader roadmap?
2. Name the four documented backend fixes and what breaks if each is regressed.
3. What's the pricing gap thesis, and which competitor comes closest to occupying it?
4. What are the open threads — where did work stop, on both the engineering and business sides?

Then tell me, in your own read: **what's the single most important thing to work on next, and why?**
Push back if my documented priorities look wrong to you. Don't just agree with the file.

---

## HOW TO MAKE THIS REUSABLE

Save Prompt 1 as a slash command so you never have to hunt for it again:

```powershell
mkdir "C:\Personal Projects\workforce-agent\.claude\commands"
# save Prompt 1 as: .claude\commands\catchup.md
```

Then any future session — after a break, after a context compaction, on a new machine — is just:

```
/catchup
```

Commit `.claude/commands/` to git and it travels with the repo, independent of any Claude account.
That's the real fix for this whole problem: context that lives in your repository can't be stranded
on an email address you lose.
