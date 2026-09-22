# Wunomo Projects — hire a team, not a chatbot

**For:** Daksh · **From:** Pratyaksh · **2 September 2026**
**Version 2** — rewritten after an architecture review. Six problems were found in v1; each one is
solved below rather than deferred.
**Decision needed:** approve Phases 0–2, or push back on the shape.

---

## The idea in one paragraph

You create a **project** in Wunomo — "Q3 Revenue Migration." You hire the agents it needs, name them,
and give each one the data it's allowed to touch. A channel opens with your team in it. You type like
you would in Slack: `@Nova profile the finance tables and flag anything that drifted`. Nova plans it,
asks permission where the action is risky, and does it. A rail on the right shows every step as it
happens, so when you come back from lunch you know exactly what each agent did while you were gone.

Not a chat window with an AI in it. A project with a staffed team.

---

## Why this is the right next build

**It makes the other five employees cheap.** AXIOM is hardcoded as one agent per tenant. LEDGER, PULSE
and the rest would each need their own wiring. If an agent is a *record* — name, type, model,
personality, scoped sources — then shipping a new employee is a config row plus its tools. We already
promised five more on the site. This is the work that makes that promise affordable.

**We own the hard part already.** The room is missing; the worker is built.

| Needed | Status |
|---|---|
| Goal → plan → approve → execute → report | Built. Three shapes reached COMPLETED against real data. |
| Approval gates with risk tiers, per-step re-check | Built |
| Board of work in flight | Built — the Tasks screen |
| Per-agent personality and operation mode | Built — already in the chat header |
| Permissions enforced in chat *and* API from one map | Built, fail-closed, tested |
| Named agent instances · channels · @mentions · live rail | Missing |

**It answers the objection every sales call will open with.** "What stops it touching production?"
Today: "the approval gate." After this: "Nova can only reach the three sources you assigned her,
enforced server-side on every call." Scope isn't a prompt instruction someone can talk the model out
of — it's the same permission map that already refuses a Viewer.

---

## Architecture decisions — the six problems, and how each is solved

These are stated as rules because they're cheap now and expensive to retrofit.

### 1. Permission is the intersection of user and agent. Never the union.

The danger: a Data Analyst tags Nova, Nova is scoped to sources the Analyst can't touch, and the agent
acts with *its* authority. That is exactly the bug we already fixed — a Viewer bypassing the role gate
by asking AXIOM — reintroduced through a new door.

**Rule:** effective permission = `has_permission(user.role, capability)` **AND**
`source ∈ agent_scope`. Both, every call. An agent can never widen what its caller may do; it can only
narrow it. `_caller_still_authorized()` extends to re-check both per step, because an agent can be
re-scoped mid-task the same way a user can be demoted.

### 2. Scope lives in a join table, not a JSON blob.

`agent_sources (agent_id, source_id)` — queryable, indexable, enforceable in SQL. Every permission
system that began as JSON in a column got rewritten. We're not doing that on purpose.

Schema, minimally: `agent_instances (id, tenant_id, project_id, name, employee_type, personality,
operation_mode, model, standing_instructions, monthly_token_budget, status)` plus `agent_sources`.
`agent_id` added to `tasks`, `chat_messages`, `llm_usage_events`, and `audit_log`.

### 3. An agent's context is filtered, not the raw channel.

If Nova reads the whole channel, and Atlas has been posting about sources Nova can't see, then Nova
reads privileged data as plain text. Our `tenant_id` force-overwrite protects the *tool* boundary;
nothing today protects the *context* boundary.

**Rule:** an agent's context contains its own messages plus the ones it was tagged in, scope-filtered.
Never the raw transcript.

### 4. Windowing gets solved before channels, not after.

We have an open finding from 14 July: agent history balloons as tool outputs accumulate — 3 → 15 → 63
messages across three turns. A project channel multiplies that by participants and by project
lifetime. At our measured 4,480 tokens per turn, a busy channel gets expensive fast and eventually
exceeds the window. Sliding window plus a rolling summary, built in Phase 0. This is the single most
likely thing to make the feature feel broken in month two.

### 5. Two agents cannot run the same source at once.

Nova and Atlas both scoped to the warehouse, both running `sync_source`. Nothing prevents that today.
A per-source advisory lock, with the second agent queued and told why. This is precisely the class of
"worked in testing" failure the audit keeps finding.

**Update, 2026-09-13 — built.** This is no longer an open problem: `services/source_lock.py` is a
real Redis advisory lock (`SET NX EX`, 300s ceiling), wired into ingestion, schema profiling, and
both transform runners. It fails fast rather than queuing as first proposed — a locked source raises
`SourceLockHeld`, which `task_executor.py` turns into `PAUSED_SOURCE_LOCKED` for later retry instead
of a live queue — but the underlying race this section describes is closed. Confirmed during the
UI-rebuild audit (`docs/design/UI_REBUILD_INVENTORY.md`).

### 6. Uploads are restricted and confirmed.

`ingest_file` handles CSV and Excel. A PDF has no destination — there's no HR or finance data model
yet. And an LLM choosing where a file lands can put it in the wrong scope. **Known types only, with an
explicit destination shown before it registers.** Related, and worth fixing in the same phase:
uploaded files currently sit on container local disk rather than a volume, so they don't survive a
rebuild. Multi-agent uploads make that worse.

---

## What we add on top — all reusing machinery we already have

**Per-agent token budgets.** The task executor already has step caps, wall-clock caps, credit caps and
loop detection. Lift them to the agent: Nova gets 40k tokens a month. One runaway agent eating a whole
tenant's quota is a support ticket we can prevent for almost nothing.

**Handoff with a human gate, instead of agents chatting.** Nova finishes and *proposes* a task for
Atlas; you approve the handoff; Atlas starts. Delegation, a full audit trail, and zero
acknowledgement-only chatter. It's our existing approval pattern applied to a new object — and it's a
better answer than what the competition demos, where half the messages are agents saying "on it" to
each other at ~4,480 tokens each.

**`agent_id` on the audit log.** "Which employee did this" is the entire compliance story for the
fintech vertical our own research names as highest willingness-to-pay. Cheap now, painful to backfill.

**Standing instructions per agent.** A short notes field folded into the system prompt: "always check
staging first," "never touch anything named `_raw`." Customers will want to teach an agent. This is
the cheapest useful version of memory.

**Offboarding designed up front.** What happens to a fired agent's running tasks, history and pending
approvals? We just answered this for delete-conversation: block while work is live, preserve the audit
record. Reuse the shape.

**Scheduled work per agent.** The unattended path is already scoped — `user_id=None`, tenant-level
quota, which is how `incident_triage` already behaves. "Nova checks freshness every morning at 8" is
what makes this feel like an employee rather than a tool, and it's closer than any of the rest.

---

## Two things I'd correct in my own idea

**"Workspace" is already taken.** In our code a workspace *is* a tenant — it's in the JWT, it owns
billing, the team, and every source. If a project were a workspace, every new project means re-inviting
people, re-connecting sources, and a separate bill. **A project is an object inside a tenant.** This
one has to be agreed before anyone writes schema.

**We can't let people hire employees that don't exist.** Finance and People Ops have no backend. The
hire screen shows them locked, carrying the same "coming soon" tag they have on the site. Version one
is *multiple DataOps agents with different scopes* — one on the warehouse, one on ingestion — which is
useful on its own. We've held the "never imply a locked employee is available" rule since day one and
I don't want to break it inside our own hiring flow.

---

## The build

**Phase 0 — foundations, nothing visible changes.** `agent_instances` + `agent_sources`. AXIOM becomes
row one. `agent_id` threaded through tasks, chat, usage and audit. Agent cache keyed by
`(tenant, agent_id)`. Context windowing. The boot-time tool assertion updated to check the union while
each instance enforces its own subset.

**Phase 1 — projects and hiring.** A project groups agents and sources inside a tenant. Create, name,
scope. Intersection permission enforced end to end, with a test that proves an agent cannot widen its
caller's authority — the same shape as the cross-consumer test we already have.

**Phase 2 — the channel.** Multiple participants, one conversation. `@Nova` routes to Nova and nobody
else. Filtered context. Per-source locking. Restricted upload with destination confirmation.

**Ship and stop here.** Phases 0–2 are the whole customer-visible idea.

**Phase 3 — the live rail.** Streaming step updates, built with auth from the first line; our last
WebSocket route was deleted for having none. Task polling covers most of it until then.

**Phase 4, only if customers ask:** handoffs, schedules, budgets as a customer-facing control.

**Not doing:** agent-to-agent conversation, a manager agent, reviewer agents, autopilot by default.

---

## What I need from you

1. **Project inside a tenant**, not project as tenant.
2. **Scope, not personality**, as the reason to create a second agent.
3. **Intersection permission** as a hard rule, written into `CLAUDE.md` alongside the other four.
4. **Phases 0–2 only**, then we stop and show it to people.

And the one I'd rather not decide alone: our ICP is a 1–10 person data team. Does a four-person team
want three named AI colleagues, or one that works properly? Scoping by data ownership maps to how they
already divide work — but that's a guess, and we've built for two months without asking anyone.

---

## The honest caveat

None of this is validated. No customers, no willingness-to-pay data, and the last two months found
four systems that looked finished and had never worked once. This is the right *next build* if the
answer to "what next" is a build at all. Ten conversations first is still cheaper, and still open.
