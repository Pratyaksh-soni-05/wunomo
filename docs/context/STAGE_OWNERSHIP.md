# Stage Ownership Map

This file is the single source of truth for who builds what in each
blueprint stage, and what security prerequisite must exist before that
stage can be built safely. Read this before starting any blueprint stage.
If a listed prerequisite doesn't exist yet in the code, stop and report —
don't improvise it.

This document reflects what the Stage 1-2 integration merge (Sept 2026)
actually found, not just what was predicted in advance. Update it the
same way — after a stage lands, record what was actually true, not just
what was planned.

## The five-instance pattern — read this first

Across this codebase's history, the identical bug has been found FIVE
independent times: a Celery/beat-scheduled function opens a bare
AsyncSessionLocal() with no tenant context established, and under RLS
the query silently returns zero rows or writes nothing — the feature
does nothing, forever, with no error anywhere.

Instances: the original freshness sweep, the scheduled-agent-task
scanner, the task auto-advance beat path, the CI/CD auto-rollback
monitor (the most consequential — a safety mechanism that silently never
fired), and GET /health/tasks.

This is now covered by a standing guard test —
tests/test_celery_tenant_context_guard.py — which discovers every
registered Celery task the same way a real worker does and fails if any
doesn't establish tenant context, with a named allowlist for the two
legitimate exceptions (anchor_audit_chains via ADMIN_DATABASE_URL, and
confirmed no-op placeholders). Any new Celery task MUST establish tenant
context via tenant_context()/async_tenant_context()/with_tenant_context()
or be added to the allowlist with written justification. The guard test
is not optional coverage — it is required to pass before any new
scheduled task merges.

## The RLS coverage pattern

Similarly, tests/test_rls_coverage_guard.py checks every table with a
tenant_id column against pg_class/pg_policies and fails if RLS isn't
ENABLE'd, FORCE'd, and policied. As of this merge: 32 tables checked,
zero violations, one documented intentional exception
(user_workspace_preferences — permissive by design, see GOTCHAS).

Any new table with a tenant_id column MUST ship RLS in the same
migration, or this guard test fails CI.

## Stage-by-stage

### Stage 0 — Secret hygiene
Status: mostly complete pre-merge (Items #1, #8). Two items found during
integration still open: a plaintext demo password in scripts/demo_reset.mjs
(not yet fixed), and the Gemini/Groq API keys never rotated (Item #8
covered JWT/Postgres/app secrets only, not LLM provider keys).

### Stage 1 — Streaming
Owner: platform. Built pre-merge on pratyaksh-workforce, integrated in
this merge.
Prerequisite that was needed: redaction on a token stream, since
redact_identifiers() only worked on an assembled response.
What actually happened: NOT delivered before Stage 1 was built (the
platform owner built ahead of the contract). Retrofitted during
Integration Phase 4 as a sliding-window buffer (_STREAM_HOLDBACK_CHARS =
64 in agent/dataops_agent.py) — the whole accumulated buffer is
re-checked against redact_identifiers() before any release, not just the
newly-released slice (redacting only the slice would let an identifier
leak character-by-character as it completes mid-stream). Live-verified
event-by-event across 80 streamed token events with a deliberately
worst-case fake model (4-char chunking, forcing every UUID across 9+
deltas): 0 leaks. Measured cost: 0.72 microseconds per call, negligible.
CONVENTION ESTABLISHED: any future streaming output path in this codebase
must use the same whole-buffer-redact-before-release pattern, not
per-chunk redaction.

Also found during integration: the residency gate (Item #11,
assert_outbound_llm_allowed()) is NOT bypassed by streaming — it lives
inside _TimeoutFallbackChatModel.ainvoke(), which streaming calls through
even though tokens still stream via LangChain's callback propagation.
This was proven from code, not just hoped.

### Stage 2 — Supervisor + Handoffs
Owner: platform. Built pre-merge, integrated in this merge.
Prerequisite that was needed: wrap_untrusted_handoff() before any
agent-to-agent output crossed a trust boundary.
What actually happened: NOT delivered before Stage 2 was built. Found,
during Integration Phase 1's analysis, that agent A's full unredacted
output was concatenated directly into agent B's goal as trusted text —
a real, confirmed agent-to-agent prompt injection path. Fixed in
Integration Phase 4: output_text now wrapped with prompt_guard's
untrusted-data tags before injection, framed as unbracketed prose inside
<tool_result> tags (bracketed [Handoff from...] framing was itself an
A4-shaped gap — Item #6 proved the model trusts bracket conventions as
authoritative). PII stripped via pii_classifier reuse before injection;
Handoff.withheld now genuinely populated (was hardcoded [] before).
Live-verified with a real, unmocked LLM call: a crafted payload combining
a fake SYSTEM override and real PII was neutralized — the raw injection
phrase is still present in the tagged block (the defense is structural
tagging, not phrase deletion) but the real model did not produce the
attacker's canary, and PII did not reach agent B.
CONVENTION ESTABLISHED: any new inter-agent data path (this supervisor or
any future one) must wrap untrusted content the same way, before it
becomes another agent's prompt input. Never inject raw agent output as
trusted context.

Also found: the supervisor's asyncio.gather fan-out (dispatch_node) and
_finalize_agent_result() both had real tenant-context/tenant_id bugs on
first live exercise (see Integration Phase 3 in GOTCHAS) — fixed and
live-verified under genuine concurrent multi-tenant load, zero mismatches
across two real tenants dispatching simultaneously.

### Stages 3-9 (live progress, workspace UI, approvals polish, Output
model, tenant isolation hardening, Command Center, Stripe+docs)
Not yet started as of this document's writing. Before starting any of
these:
- Confirm both guard tests still pass on the branch you're starting from.
- Any new table: RLS in the same migration, or the guard test blocks you.
- Any new background/scheduled task: tenant context established, or the
  guard test blocks you.
- Any new inter-agent or inter-service data handoff: wrap untrusted
  content per the Stage 2 convention above.
- Any new streaming output path: whole-buffer redaction per the Stage 1
  convention above.
- Blueprint Stage 7 ("tenant isolation hardening") is largely superseded
  by the RLS work already merged — check what, if anything, from that
  stage's original scope still applies before building it as originally
  described.

## Standing rules (unchanged from the original integration contract)

1. Every new tenant_id table ships RLS in the same migration — enforced
   by test_rls_coverage_guard.py.
2. Never open a bare AsyncSessionLocal() for tenant-scoped reads or
   background work — enforced for Celery by
   test_celery_tenant_context_guard.py; not yet enforced for request-path
   code (still a code-review discipline).
3. Never return an error as HTTP 200. Raise HTTPException.
4. Never create a second hand-maintained list of tool/model/capability
   names. Derive from the single source, or guard-test it.
5. All sessions mint through issue_token_and_remember().
6. Announce before generating a migration; add new .env keys to
   .env.example in the same commit.

## Open decisions made during this merge, for the record

- Hard Rule 2 (LLM provider routing): master's declared-provider-setting
  mechanism was kept; the platform branch's independent name-prefix-
  inference fix for the same bug was dropped in favor of it.
- log_llm_usage() failure semantics: composed, not picked — master's
  re-raise-on-permission-denial preserved, platform's Redis
  dropped-event counter attached only to the transient-error branch.
- EMPLOYEE_TYPE_TOOLS-style hand-curated allowlists: blessed as an
  acceptable pattern going forward, specifically because it's fail-closed
  at import time (crashes rather than silently under-gating) and derived
  from existing RBAC tiers — not a fresh hand-list.

## Post-merge infrastructure findings (2026-09-27)

- **Connection-pool exhaustion — a genuine infrastructure capacity finding,
  distinct from the five-instance tenant-context pattern above.** Celery's
  prefork model multiplies per-process pool sizing by worker count:
  backend, celery_worker (--concurrency=4, four independent OS processes),
  and celery_beat each independently import database.py and build their
  own SQLAlchemy engine/pool. At pool_size=10/max_overflow=20 that was a
  30-connection ceiling per process — five processes deep for a worst-case
  150-180 against Postgres's default max_connections=100. Fixed via
  database.py's non-test branch (pool_size/max_overflow reduced to 5/5,
  ceiling 10/process) plus docker-compose.yml's postgres service
  (max_connections raised to 200). Worth knowing before spinning up any
  additional service/worker in a future stage — the same multiplication
  applies to any new process that imports database.py.

- **Two CI workflows now in place.** guard-tests.yml runs the two standing
  guard tests on every push/PR (~15s). full-suite.yml runs the complete
  suite post-merge (push to master), nightly, and via workflow_dispatch —
  deliberately not per-PR, given the cost. full-suite.yml runs inside a
  job-level `container:` block (python:3.11-slim, matching backend/
  Dockerfile's own base image) specifically so it shares the same Docker
  network as its service containers and hostnames like "postgres"/"redis"
  resolve exactly as they do locally under docker-compose — the bare
  ubuntu-latest runner alone only has localhost port-forwarding to
  service containers, which broke any test asserting against the real
  docker-compose service name (Hard Rule 4's own convention). **Any new
  test requiring a real external credential** (an LLM API key, a webhook
  URL, SMTP) needs one of two treatments in full-suite.yml, matching the
  distinction the suite already makes elsewhere: a CI-only dummy value
  added to the workflow's env block, if the test only needs client
  construction/config-shape to succeed and never a real call (the
  established pattern for CREDENTIAL_ENCRYPTION_KEY, GEMINI_API_KEY,
  GROQ_API_KEY, SLACK_WEBHOOK_URL, SMTP_*) — or an explicit live_llm-style
  pytest marker excluding it from CI entirely, if it genuinely needs a
  working credential and real network access.

- **Confirmed finding: the two previously-known local test flakes did not
  reproduce in any of three fresh, real CI runs** —
  test_check_scheduled_agent_tasks_invalid_cron_does_not_crash and
  test_total_runnable_count_reflects_the_real_backlog_not_just_the_capped_batch.
  Both are attributable to accumulated local dev-DB state, not a real code
  defect — consistent with the same tenant-accumulation/no-teardown
  problem documented in GOTCHAS.md, not a new concern.
