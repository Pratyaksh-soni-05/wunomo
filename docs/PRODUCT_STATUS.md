# AXIOM / Wunomo AI — Product Status (honest inventory)

Written 2026-07-23/24 ahead of the YC application, for the founder's own use
in answering application questions accurately. Every claim below is either
live-verified this session/prior sessions (see `CLAUDE.md`'s Status Table for
the detailed evidence trail) or explicitly marked as not yet built. Nothing
here is written to sound impressive — where the honest answer is "not done"
or "broken," it says so.

---

## a. What genuinely works end-to-end today, live-verified

**Auth & multi-tenancy.** Three real signup/login methods — password,
Google OAuth (real consent-screen click-through, real token exchange),
email-code via Resend (real delivered email, real code round-trip). JWT-based
sessions, 5-role RBAC (Owner/Admin/Data Engineer/Data Analyst/Viewer)
enforced identically on both the REST API and AXIOM's own tool-calling path
via one shared permission map — not two rulebooks that happen to agree.
Removed/demoted users lose access on their *next request*, not just their
next login (a real DB re-check per request, confirmed via SQL-echo capture
showing exactly one extra query, not N).

**Real data pipelines.** Upload a CSV/Excel file (or connect Postgres/MySQL/
a REST API/Google Sheets), profile its schema, build a pipeline, run it on a
schedule or on demand, watch quality rules check the actual data, see the
run history with real row counts and durations. Failures produce real error
messages (a genuinely bad file path fails with "File not found: ...", not a
generic "something went wrong").

**AXIOM, the AI agent, actually calls real tools against real data.** This
is the core of the product and it's real: 38 tools spanning ingestion,
transformation, quality, orchestration, observability, and governance, each
calling the same service-layer code the REST API uses (no tool fakery, no
separate "demo mode" logic). A chat conversation about "why did this
pipeline fail" genuinely queries the real incident, the real run history,
and produces a diagnosis grounded in the real error — not a canned response.
Verified across hundreds of real LLM calls (both Gemini and Groq) over many
sessions, not a handful of cherry-picked demos.

**Human-in-the-loop governance — the gate itself is real.** A configurable
risk tiering (low/medium/high) plus 4 operation modes (Advisory/Assisted/
Autonomous/Audit) determines whether a given AXIOM action requires human
sign-off before executing. When it does, a real, timestamped, audited
approval request is created and blocks the action. Role permissions are
checked *before and independently of* the risk gate, so a Viewer chatting
with AXIOM can't get it to do something the same Viewer would be blocked
from doing through the UI.

**Data lineage, auto-populated.** Creating a source or pipeline
automatically registers it in a real lineage graph (nodes + edges), with a
self-healing sync so pre-existing tenants backfill correctly on read — not
a static demo diagram.

**Team, billing, settings — all real for a single-tenant SaaS.** Invite
teammates (real Resend delivery, real accept flow), role management,
3-tier plan/quota enforcement calibrated against this project's own real
usage data (not guessed numbers), workspace/notification/AI-model/theme
settings, API key generation (see caveat in section b).

**CI/CD risk-gating.** A real webhook-triggered pipeline that runs quality/
schema/lint/complexity checks on an incoming commit, computes a real risk
score, and auto-deploys or requires approval based on that score — with
real automated rollback on a post-deploy health failure.

---

## b. Built but not production-ready

**Approving a blocked AXIOM action doesn't currently execute it.**
Found live this session while preparing the demo: the dynamic dispatch that
resolves an approved action's tool call (`PolicyEngine.execute_approved_action`)
looks for a plain module-level function, but every real target is a class
method — so all 8 registered action types fail to dispatch. The approval
*record* is completely real (created, reviewed, timestamped, audited); the
"and now it runs automatically" half of the story is not wired up. This is a
contained, well-understood bug (one function's dispatch logic), not a design
flaw in the governance model itself — but it means "approve and AXIOM acts"
is not something to claim works today.

**API keys are a CRUD feature, not an auth mechanism yet.** You can
generate, list, and revoke a platform API key, and the raw secret is
provably never persisted or exposed in the client. But nothing in the
backend currently *accepts* one of these keys as a request credential —
there's no `Authorization: Bearer axm_live_...` support anywhere yet. This
is a real, separate, phase-sized piece of work (a new auth dependency, a
decision on key-scoped permissions, rate limiting), not a footnote.

**Billing is a real state machine with no real payment behind it.**
Plan upgrades/downgrades take effect immediately and for real — this isn't
theater — but there's no Stripe integration: `POST /billing/checkout`
honestly returns a 501, and `change-plan` doesn't validate that a downgrade
wouldn't immediately strand the tenant over its new limits (a real gap, not
yet fixed — the UI shows a non-blocking warning, not a hard block).

**The WebSocket chat endpoint is unauthenticated.** `main.py`'s
`/ws/chat/{tenant_id}/{session_id}` takes `tenant_id` from the URL with no
JWT check at all — anyone who finds the endpoint can chat as any tenant.
Partially narrowed (forced to Viewer-tier tool access only) but not fixed.
The REST API and the primary chat endpoint (`POST /chat/`) have no such
gap — this is specific to the WebSocket route, which nothing in the current
frontend actually uses.

**Multi-tenant data isolation is convention, not framework-enforced.**
Every tenant-scoped query has to remember to filter by `tenant_id` — there's
no Postgres row-level security, no base query class, no middleware that
would catch a forgotten filter. Every current query path has been
spot-checked and is correct, but the *pattern* has no safety net for future
code. This is a real architectural debt worth knowing about, not a live bug.

**A raw, unhandled 500 is still possible from `POST /chat/`.** One concrete
trigger (empty-list tool results) was found and fixed this session. The
general case — *any* unrecovered failure from both the primary and fallback
LLM in the same request — still has no top-level exception handler on the
backend; the frontend degrades gracefully (a clear inline error, composer
stays usable), but the backend itself doesn't persist a message or log the
failure in a structured way for that case.

**Tenant scoping inside the LLM cost model is coarse.** A single
multi-tool-call chat conversation can cost 25,000+ AI credits (the whole
default Starter-tier monthly allowance) because every LLM call in a
tool-calling turn resends the entire system prompt and all 38 tool schemas
as input tokens. The credit math and quota enforcement are real and correct
— the underlying per-call cost is just higher than the current tier
defaults anticipated, found live this session.

**Both LLM providers are real operational constraints, not theoretical
ones.** Gemini's free tier is a flat 20 requests/day; Groq's shared,
org-wide daily token budget (100,000 tokens) has been fully exhausted by a
single afternoon of verification testing more than once. Any customer-facing
usage at real scale needs a paid tier on at least one provider before it's
viable beyond a demo.

---

## c. Designed but not built

**The 5 additional AI Employees** (LEDGER, DEPLOY, INSIGHT, SENTINEL,
PULSE) — named, described, and shown as honestly-locked "Coming Soon" tiles
in the product. Zero backend exists for any of them. AXIOM is the only real
employee today.

**Automations** (a general trigger→action rule engine) — explicitly scoped
as a dedicated future project, not started.

**Compliance tab** (within Governance) — not built, listed as
Coming-Soon-at-launch from the original design sign-off.

**A real DAG execution engine.** Despite the name `DAGManager`, pipeline
"execution" today is a fixed linear sequence (sync → quality check → done)
— no dependency graph, no branching, no parallel steps. Fine for the
current single-source-per-pipeline model; would need real work to support
multi-step/multi-source pipelines.

**Privacy Policy / Terms of Service.** The public landing page links to
real signup/login, but no legal pages exist yet and neither auth flow
requires accepting one — flagged as required before real production
signup traffic, not attempted without the founder's own input on the
actual legal content.

**Production deployment.** Everything above has been built and verified
against a local Docker Compose stack. There is no production deployment,
no domain, no live URL — gated on the founder acquiring a domain, tracked
explicitly as an open item, not silently assumed away.

---

## d. Five most impressive things, stated plainly (for a technical evaluator)

1. **The permission model is unified across two structurally different
   surfaces — REST and an LLM tool-calling agent — sharing one map, with a
   test that proves it.** Most "AI + RBAC" demos gate the chat UI's buttons
   but leave the agent's own tool execution ungated, or hand-roll two
   separate rule sets that quietly drift apart over time. Here, both the
   REST layer and the agent's tool-dispatch loop consult the exact same
   `PERMISSIONS`/`TOOL_CAPABILITIES` dictionaries, verified by a dedicated
   regression test that asserts a blocked action fails identically through
   *both* paths against the same underlying map — not two independent
   implementations that happen to agree today.

2. **The tenant-identity trust boundary is enforced at the LLM's own
   argument level, not just at the API gateway.** Tool schemas require the
   LLM to supply `tenant_id` as a function-call argument — an LLM has no
   reliable way to always get this right, and testing this from-scratch
   proved it: a tenant with real data got "0 results" from chat before this
   was fixed, because the model occasionally hallucinated `tenant_id`. The
   fix — force-overwriting the LLM's own argument with the real,
   JWT-derived value on every single tool call, server-side, after the LLM
   emits it — closes an entire class of prompt-injection/hallucination risk
   that's easy to miss if you only think about "did we check the user's
   auth," not "can the AI itself be tricked into acting on the wrong
   tenant's behalf."

3. **A real, live-diagnosed and fixed LangChain/provider-integration bug
   class, not a framework taken on faith.** Migrating to LangChain v1.x for
   Gemini 3 tool-calling surfaced two genuinely subtle bugs — Gemini's
   responses coming back as structured content blocks instead of plain
   strings (crashing message persistence), and `langchain-google-genai`
   silently stringifying dict/list tool arguments (proven, not assumed, by
   comparing against a raw Gemini API call bypassing LangChain entirely).
   Both were root-caused and fixed with targeted, tested code — the kind of
   integration debugging that separates "wired up an SDK" from "understands
   what's actually happening inside it."

4. **The approval-gate risk tiering is evaluated independently of, and
   before, the operation mode — and it's provably not theater.** A Viewer
   in Advisory mode gets every single action blocked; a Data Engineer in
   Assisted mode only gets medium/high-risk actions blocked; the actual
   dispatch that would execute an approved action is separate code from the
   gate that decides *whether* to block — meaning the security boundary
   (can this role do this at all) and the workflow boundary (should this
   specific action pause for review) are genuinely decoupled, not
   conflated into one if-statement that's easy to get subtly wrong.

5. **Nothing in this codebase's documentation claims something works
   without saying how it was checked — and that discipline caught real
   bugs.** The project's own working notes (`CLAUDE.md`) treat "I read the
   code and it looks right" as fundamentally different from "I ran it
   against the real stack and watched it work," and that distinction is
   what surfaced an entire cluster of previously-undetected bugs (enum
   case-sensitivity mismatches across 6 files, a tool-call dispatch mechanism
   that had never actually been exercised end-to-end, a cost model that
   quietly costs 10x what its own tier limits assumed). Most projects at
   this stage have optimistic documentation; this one has an unusually
   accurate one, including the parts that are unflattering — which is
   itself a signal about how the product was actually built.

---

## A note on how this document was produced

Everything above is either directly reproduced from live testing performed
in this session (the approval-dispatch bug, the empty-list crash, the
`rows_processed` bug, the credit-cost finding, the RISK_ACTIONS naming
mismatch) or drawn from `CLAUDE.md`'s Status Table, which itself only marks
something "done" after a specific, named, reproducible live test — not a
code read. If a claim in a future YC application answer needs a citation,
`CLAUDE.md`'s Status Table has the specific test, request, or command that
proved it, phase by phase.
