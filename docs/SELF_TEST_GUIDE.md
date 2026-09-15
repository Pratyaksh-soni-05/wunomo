# AXIOM Self-Test Guide

Rewritten from scratch 2026-09-15 (slice 13 of the Wunomo UI rebuild) rather than patched —
the previous version was written against a sidebar with ~19 nav items and no concept of
Projects or Workbench; six of its destinations have since retired to real homes elsewhere,
and almost every navigation instruction in it no longer matches what's on screen. This
version is structured around what a real user actually does, in the order they'd do it, not
the order features were built.

**How to read a step.** Every numbered step has three parts: **Click** (the literal button/
field text, verbatim from the real code — if it says **Approve Plan**, that's the exact text
on screen, not a paraphrase), **You should see** (what a correct result looks like), and **If
it looks wrong** (a specific thing to check before assuming you found a bug). If you hit
something not covered by an "if it looks wrong" note, check the **Known Issues** appendix at
the bottom before reporting it fresh — seven things in there are already known, and telling a
new discovery apart from one of those six saves a lot of back-and-forth.

**Cost callouts.** A 💰 marks any step that makes a real LLM call — this product's actual
spend, not a simulated one. Each callout names the call and keeps a running count of real LLM
calls made so far in the walkthrough. It's a **call count**, not a dollar figure — the real
AI-credit number (`input_tokens × 1 + output_tokens × 3`, shown on Team & Billing's Usage tab
and on each task's own Cost card) depends on response length, which this guide can't predict
ahead of you actually running it. Watch that number in the product itself; use the running
count here to sanity-check roughly how many calls you've made.

**Before you start:**
```bash
cd dataops-agent
docker compose up -d --build              # backend + postgres + redis + celery
docker compose ps                          # confirm all 5 containers say "Up"
curl http://localhost:8000/health          # {"status":"ok",...}
```
```bash
cd frontend
npm run dev                                # separate terminal — not a Docker service
```
Open `http://localhost:3000`.

---

## 1. Sign up, land on Home

**1.1 — Create your account.**
**Click:** On `/signup`, fill in **Full name**, **Email**, **Workspace name**, **Password**,
then **Create account**.
**You should see:** You're redirected straight to `/onboarding` — this is not skippable for a
brand-new workspace.
**If it looks wrong:** If you land on `/home` instead, your test email already has a
completed onboarding record from a prior run — use a fresh email.

**1.2 — Onboarding, 4 steps, no skip button anywhere.**
1. **What's your role?** — pick one chip (Data Engineer / Data Analyst / Data Scientist /
   Engineering Manager / Founder / CEO / Other).
2. **What industry are you in?** — free-text field.
3. **How big is your company?** — pick one chip.
4. **How will Wunomo AI help you?** — pick at least one chip (required). Below it, **Which of
   these does your data stack include? (optional)** — this one's genuinely optional, the only
   one in the flow.

**Click: Next** on each step (**Back** is available but disabled on step 1; the last step's
button reads **Finish**). It stays disabled until that step's required field is filled.
**You should see:** Finishing redirects to `/home`.
**If it looks wrong:** If **Next**/**Finish** stays disabled and you've filled everything
visible, check step 4 specifically — the use-cases chips are the one required multi-select,
easy to miss since the data-stack chips right below them look identical but aren't required.

**1.3 — Home.**
**You should see:** `Welcome back, {the part of your email before the @}` — not your onboarding
role or a display name, deliberately just the email's local part. Below it: a **Start a new
project** card, a **Recent** section (empty for a fresh account — *"No projects yet — start one
above."*), and a **Workspace health** text link at the bottom (goes to `/dashboard`, the old
KPI page — separate from everything else in this guide, not covered further here).
**If it looks wrong:** Project cards' agent/source counts can show "…" for a second before
settling on a fresh page load — that's real per-card fetch latency (no aggregate endpoint
exists yet for this), not a bug, unless it never resolves.

💰 *No LLM calls in this section. Running total: 0.*

---

## 2. Create a project

**2.1 — Start one.**
**Click:** The **Start a new project** card on Home (or **+ New Project** on `/projects`).
**You should see:** A **New Project** modal with **Name** (required, e.g. "Q3 Revenue
Migration") and **What's this project for? (optional)** — a one-line description your agents
will read as context. Click **Create**.
**You should see:** A toast confirming creation, and you land on the project's **Chat** tab
(`/projects/{id}/chat`) — Chat is the deliberate default tab, not Agents, even though nothing
in it is built out yet at this point in the walkthrough. You'll come back to it in Section 4.

**2.2 — Look at the project shell.**
**You should see:** Four tabs — **Chat**, **Workbench**, **Tasks**, **Agents** — and a header
with the project name and an **Hire agent** button. The project now also appears under
**PROJECTS** in the sidebar.
**If it looks wrong:** If Workbench looks empty with a message about no agents, that's
correct and expected — you haven't hired one yet. Section 3 fixes that.

💰 *No LLM calls in this section. Running total: 0.*

---

## 3. Hire an agent, scope it

**3.1 — Open the hire flow.**
**Click: Hire agent** in the project header (or **+ Hire Agent** on the global `/agents`
list — same modal either way, just pre-filled with a project or not).
**You should see:** A **Hire an agent** modal. Near the top: *"Only DataOps is available
today — the rest are shown for context, not selectable."* above a row of 6 employee-type
cards (DataOps active, 5 marked **Coming Soon** and non-interactive).

**3.2 — Fill it in.**
- **Name** (required) — e.g. "Nova".
- **Project (optional)** — should already show the project you came from; leave it.
- **Data source scope** — a checkbox list of every source your tenant has connected. If this
  is your first agent, the list is empty: *"No sources connected yet. **Connect one** to
  scope this agent's access — or hire now with no scope."* That's fine — go ahead and hire
  with zero sources checked for now; Section 3.3 below (via Workbench) is where you'll
  actually connect one. **Don't click "Connect one"** — it links to the old, retired
  `/sources` route, which will just bounce you back out with a toast; it was never repointed
  after Sources moved into Workbench (same gap on the agent detail page's own "Data source
  scope" card, used in 3.4). Not a broken link exactly, just a dead end worth knowing about
  rather than clicking through curiosity.
- **Monthly token budget (optional)** — leave this blank for now. You'll come back to this
  exact field in Section 9 to deliberately set a tiny one.

**Click: Hire.**
**You should see:** A toast — `Hired "Nova".` — and the modal closes.
**If it looks wrong:** The **Hire** button stays disabled until Name is non-empty; nothing
else in this modal blocks it.

**3.3 — Connect a real source (needed for the rest of this guide).**
**Click:** Project → **Workbench** tab → **Sources** (first item in the Workbench sub-nav) →
**+ Add Source**.
**You should see:** A form with a **Type** dropdown (CSV file, Excel file, Postgres, MySQL,
REST API, Google Sheets). Pick **CSV file**, choose any small real CSV on your machine, give
it a name, and click **Upload & Create**.
**You should see:** A toast noting the source was created but *"not scoped to any agent yet —
it won't show here until you grant it from the Agents tab."* This is real, not a bug — sources
and agent-scope are deliberately separate steps.

**3.4 — Grant the source to Nova.**
**Click:** Project → **Agents** tab → **Nova** → **Data source scope** card → check the box
next to the source you just uploaded.
**You should see:** Back in Workbench → **Sources**, your new source now appears, with a count
badge next to "Sources" in the sub-nav.
**If it looks wrong:** If the source never appears here even after granting, re-check you
granted it to *this project's* agent, not a different one — grants are per-agent, and this
Workbench tab is filtered to whichever agents belong to this project.

💰 *No LLM calls in this section (hiring, uploading, and granting are all plain CRUD — no
model call involved). Running total: 0.*

---

## 4. Chat: tag it, upload a file, get a real reply

**4.1 — Go back to the project's Chat tab.**
**You should see:** A signpost-style empty composer area with a **Channels** section in the
left panel — the project's Chat tab is built around **channels**, not a single unnamed
thread. `AXIOM Direct` (1:1, unscoped chat) lives at the separate top-level `/chat` and is
deliberately **not** shown here — a project's Chat tab only ever shows channels that belong
to it.

**4.2 — Create a channel.**
**Click:** The **+** next to **Channels** in the left panel.
**You should see:** A **New Channel** modal — **Name** (required) and a checklist of your
project's agents (at least one required — the hint below it says so: *"A channel with no
agents can't be talked to."*). Name it something like "warehouse-check", check **Nova**, and
click **Create**.
**You should see:** The channel opens automatically, showing **# warehouse-check** in the
left panel.

**4.3 — Send a message that @mentions Nova.**
**Click:** In the composer, type `@Nova check the source I just connected` and send.
**You should see:** Since Nova is the channel's only member, the @mention isn't strictly
required for routing (a single-member channel auto-routes), but typing it is the honest
habit for when you add a second agent later (Section 8). A real reply streams in from Nova.

💰 **Cost: 1 real LLM call** (Gemini 3.5 Flash primary, Groq `openai/gpt-oss-120b` fallback
on timeout). **Running total: 1.**

**4.4 — Upload a file into the channel.**
**Click:** Drag a small CSV onto the composer (or use the attach control, if present) and
send it with an accompanying message like "profile this."
**You should see:** The file registers as a new source, silently scoped to Nova (the
resolved agent for this channel), and gets profiled immediately — a toast along the lines of
*"Nova is ready with '{filename}' on your next message."* No LLM call happens for the upload
itself.
**If it looks wrong:** File uploads only work **inside a channel** — the composer will refuse
with *"File uploads are only supported inside a channel right now"* if you try this on a
1:1 AXIOM Direct thread. That's expected, not a bug (see Section 9.4 for what a genuinely
*rejected* file type looks like, which is different from this).

**4.5 — Confirm a real reply landed, and check the Activity/Data/Agents side panel.**
**You should see:** A three-tab side panel — **Agents** (Nova's card, live status, source
count), **Data** (the sources this project's agents can reach, including what you just
uploaded), **Activity** (task steps and tool calls, chronological, currently a two-part list
if anything ran).

💰 *Section running total after Section 4: 2 real LLM calls (2 messages sent, assuming you
sent exactly one in 4.3 and one in 4.4's accompanying message — adjust upward by however many
extra messages you actually sent; each one is another real call).*

---

## 5. Give it a task: plan, approval gate, completion, cost

**5.1 — Open the task-creation modal.**
**Click:** Project → **Tasks** tab → **+ New Task** (or the equivalent control from chat, if
you started this from a conversation).
**You should see:** A **Start a Task** modal:
- **What should AXIOM do?** — a goal textarea. Hint below it: *"AXIOM will generate a real,
  reviewable multi-step plan — nothing runs until you approve it."*
- **Task type** — a dropdown with exactly 3 real options: **Diagnose pipeline failure**,
  **Investigate incident**, **Sync, profile & quality-check a source**.
- **Agent** — pick Nova.

**Pick "Sync, profile & quality-check a source"** specifically, not the other two — this is
the one shape whose plan reliably includes a step the approval gate in step 5.4 needs to be
real (see the note there for why the other two shapes won't trigger it).

Type a goal like *"Profile the source I uploaded and run a quality check on it"* and click
**Generate Plan**.

💰 **Cost: 1 real LLM call** (task planning — same Gemini 3.5 Flash → Groq routing as chat).
**Running total: 3.**

**5.2 — Review the generated plan.**
**You should see:** A toast — `Plan generated — review it before approving.` — and the task
detail page shows a numbered list of steps, each naming a real tool
(`sync_source`/`profile_schema`/`run_quality_checks`, drawn only from this task shape's fixed
allowlist — the plan can never invent a tool outside it).
**If it looks wrong:** Picking the wrong agent here is a mistake you can't fix after the
fact — a task created against an agent that can't reach the goal's source will hit a
permanent scope denial (see Section 9.1). Double-check the **Agent** field before generating.

**5.3 — Approve the plan.**
**Click: Approve Plan.**
**You should see:** A toast — `Plan approved — queued for execution.` — status moves to
`QUEUED`, not `RUNNING` yet (nothing auto-advances; a human has to drive each step).
**If it looks wrong:** **Reject Plan** is the other option here — if you click it by mistake,
the task terminates permanently (`PLAN_REJECTED`); there's no "un-reject," you'd start a new
one.

**5.4 — Advance the task and hit the approval gate.**
**Click: Advance one step** (or **Run to completion** to drive it all at once).
**You should see:** `sync_source`/`profile_schema`/`run_quality_checks` are all **medium
risk** — the approval gate applies unconditionally to any medium/high-risk tool, regardless
of agent settings — so one of these steps should pause with status
`PAUSED_NEEDS_APPROVAL`. A card appears: **Approve or reject this step**, with an optional
notes field and **Reject Step** / **Approve & Resume** buttons.
**If it looks wrong:** If your account isn't Owner or Admin, you won't see those buttons —
you'll see *"This step needs approval from an Owner or Admin before the task can continue."*
That's correct: approval is deliberately never creator-only, so log in as an Owner/Admin
account to actually approve it. Separately — **"Diagnose pipeline failure" can never reach
this gate at all**, every tool in that shape is risk-low by design; if you picked that shape
in 5.1 instead, you won't see an approval step, and that's not a bug.

**Click: Approve & Resume.**
**You should see:** A toast — `Step approved — resuming.` — and the task keeps advancing.

**5.5 — Run to completion and check the real cost.**
**Click: Run to completion** if you haven't already.
**You should see:** Status reaches a terminal state (`COMPLETED`, ideally). A **Cost** card on
this page shows **`{N}` AI Credits**, **`{N}` LLM call(s)**, input/output token counts. The
credit formula is `input_tokens × 1 + output_tokens × 3` — a deliberate placeholder proxy, not
real currency.
**If it looks wrong:** No additional LLM calls happen during advance/approve/resume/reject —
the single planning call in 5.1 is the only model cost this entire task incurs. If the Cost
card shows more than 1 LLM call, that's unexpected for this flow specifically (it can be
correct for other task shapes that call an LLM mid-execution — not this one).

💰 *No further LLM calls in 5.3–5.5 — the plan itself never re-calls the model.
Running total after Section 5: 3.*

---

## 6. Workbench: the 9 surfaces, project-scoped

Every surface below is filtered to **this project's** resolved sources (via its agents'
grants) — nothing tenant-wide leaks in, and nothing outside this project's scope should ever
appear. All 9 live under the Workbench tab's own sub-nav, in this order:

**6.1 — Sources.** Already used in Section 3. **+ Add Source**; existing rows show sync/profile
row actions.

**6.2 — Pipelines.** **+ New Pipeline** — name, pick a source from *this project's* sources
only, optional cron schedule. A pipeline created with **no source selected** is real and
allowed (shows "No source (manual, unscoped)" in the picker) — it becomes tenant-wide
*unscoped*, visible instead at the top-level `/pipelines` route, with a note in this tab:
*"+ N pipeline(s) not tied to any project."*

**6.3 — Quality.** **+ New Rule**, attached to one of this project's pipelines — no unscoped
case here (a quality rule always requires a pipeline at creation).

**6.4 — Incidents.** **+ Log Incident** — same "leave Pipeline blank to make it unscoped"
option as Pipelines, same "+ N unscoped" note, same tenant-wide home at `/incidents`.

**6.5 — Transforms.** Four tabs — **Natural Language**, **SQL Editor**, **Python Editor**,
**History** — source picker restricted to this project. **If it looks wrong:** the top-level
`/transforms` route no longer exists (it was retired outright, not repurposed like Pipelines/
Incidents — every real transform run always has a source, so there was never a genuine
unscoped population to give it a separate home for).

**6.6 — Lineage.** A table: Source → Pipeline → Output → Status, where Status is either
**Approximate** (this project's own pipelines, always — lineage here is derived from
registration metadata, not real query-tracing, and every pipeline visible in a project
already has a source by construction) or **Unresolved** (a second table below, for tenant-
wide unscoped pipelines specifically — a pipeline with no source literally cannot resolve
lineage, so this is the one place "Unresolved" is real and reachable).

**6.7 — CI/CD.** Commits and Deployments tabs, with health/rollback/approval stat cards.
**If it looks wrong:** there's no manual "create a commit" button anywhere — commits only
arrive via a GitHub webhook. On a fresh account with no webhook configured, this tab will
show empty states in both sub-tabs, and that's correct, not a bug — this is the one Workbench
surface you can only observe, not manually generate data for for the purposes of this guide.

**6.8 — Contracts.** **+ New Contract** — name, a **Producer source** dropdown (required,
restricted to this project's sources), optional consumer description. Click the checkmark row
action to **Validate**.

**6.9 — Catalog.** A searchable table of every table/column this project's sources have
registered, with a **Sync Metadata** button that profiles every source in one pass. A source
that's never been profiled shows a **Not profiled** badge instead of hiding.

**If any of 6.2–6.9 looks wrong across two different projects:** the specific thing worth
checking is the negative control — something scoped to Project A should never appear in
Project B's own tabs, even though both queries hit the same tenant-wide tables underneath.
If you have two projects with different agents/sources, spot-check one surface (Pipelines is
the easiest) by confirming a Project-A-only pipeline is genuinely absent from Project B.

💰 *No LLM calls anywhere in Workbench — every action here is plain CRUD or a deterministic
tool call, not a model call. Running total unchanged: 3.*

---

## 7. Hire a second agent with a different scope, prove the boundary

**7.1 — Create a second project and a second source.**
**Click:** `/projects` → **+ New Project** → name it something distinct (e.g. "Ingestion
Cleanup"). Inside it, Workbench → Sources → **+ Add Source**, upload a different file.

**7.2 — Hire a second agent scoped only to the new source.**
**Click: Hire agent** from this second project's header. Name it (e.g. "Orion"), grant it
**only** the source you just created in 7.1 — leave Nova's source unchecked.
**You should see:** Orion's Workbench (this project) shows only its own source; the first
project's Workbench still shows only Nova's.

**7.3 — Prove the boundary, not just describe it.**
Go back to Project A's Workbench → Sources. **You should see:** Orion's source is absent.
Go to Project B's Workbench → Sources. **You should see:** Nova's source is absent.
**If it looks wrong:** if either source leaks into the wrong project, that's a real scoping
bug worth reporting immediately — this exact cross-project boundary is the single
most-verified guarantee in this product (every Workbench surface's own build was checked
against it individually before shipping).

💰 *No LLM calls in this section. Running total: 3.*

---

## 8. Channels: two agents, @mention routing

**8.1 — Hire a second agent into Nova's own project, then create a fresh channel with both.**
Section 7's Orion belongs to a different project, and channel membership hasn't been checked
against cross-project agents for this guide — sidestep the question entirely by hiring a
second agent (e.g. "Atlas") directly into Project A, same as Section 3. **Click:** back in
Project A's Chat tab, **+** next to **Channels** → name it (e.g. "two-agent-test") → check
**both** Nova and Atlas → **Create**.
**You should see:** the channel lists 2 active agent members.

**8.2 — @mention one specifically.**
**Click:** Type `@Nova ...` (using whichever of the two agents you want to address) and send.
**You should see:** Only Nova replies — the other agent stays silent for this message. The
composer's autocomplete should also have suggested Nova's name as soon as you typed `@N`,
filtered to this channel's real members.

💰 **Cost: 1 real LLM call.** **Running total: 4.**

**8.3 — Send a message with no @mention at all, now that there are 2 members.**
**You should see:** The message is refused with a real routing error, not silently sent to
whoever: *"More than one agent is in this channel — please @mention who you're talking to."*
This is the exact real backend message, not a paraphrase.

**8.4 — Try mentioning a name that isn't in this channel.**
**Click:** Send `@Atlas hello` where "Atlas" is either not a real agent name, or a real agent
that exists in your tenant but isn't a member of this specific channel.
**You should see:** Two different real messages depending on which case you hit — a genuine
typo/unknown name gets *"'{name}' doesn't match any agent in your workspace."*; a real agent
that just isn't in this channel gets *"{Name} exists but isn't a member of this channel yet.
Add them from this channel's members, then @mention them again."* These are deliberately
worded differently so you can tell a typo apart from a fixable membership gap.

💰 *Routing failures in 8.3/8.4 never reach the LLM — they're rejected before any model call.
Running total after Section 8: 4.*

---

## 9. Failure paths: scope denial, source lock, budget exhaustion, PDF rejection

**9.1 — Scope denial (permanent, can't be undone by the fix that caused it).**
**Click:** Create a new task (Section 5's flow) on an agent, but write a goal that plainly
needs a source that agent was never granted — or simpler: create the task normally, then
**revoke** the agent's grant to the source the plan already resolved against (Agents tab →
revoke), then advance the step.
**You should see:** The step fails with a message naming the exact denial, and the task
lands in `PAUSED_FAILED_STEP` with a plain, explicit sentence: *"This task can't be
resumed — start a new one once the underlying problem is fixed."*
**This is real and deliberate, not a bug to report:** re-granting the source does **not**
unblock this specific task — only a brand-new task can use the fix. This is the single most
important thing to internalize about this product's failure model; it's tracked as **Known
Issue #76** below, not something to file again.

**9.2 — Source lock (timing-dependent — read this before trying it).**
This one requires two operations racing against the **same source** at the same time, which
is inherently awkward to demo by hand with certainty. **Click:** Open two browser tabs on the
same project. In tab 1, trigger a sync/profile/transform against a source. Within a second or
two, in tab 2, trigger a *different* operation against that exact same source.
**You should see, if the timing lands:** The second operation's step pauses at
`PAUSED_SOURCE_LOCKED` with a message like *"This source is currently in use by {agent}
(since {time})."* The task automatically resumes once the first operation finishes — no
manual unblock needed, unlike 9.1.
**If it looks wrong:** if both operations just succeed independently, you likely didn't win
the race — the lock only fires on genuine overlap. This isn't reliably reproducible on the
first try; that's the nature of the thing being tested, not a guide error.

**9.3 — Budget exhaustion (agent-level, deterministic and easy to trigger on purpose).**
**Click:** Hire a **third** agent (or edit — if no edit exists, hire fresh) with **Monthly
token budget** set to a deliberately tiny number, e.g. `50`. Then send it one real chat
message.
**You should see:** The first message likely succeeds (💰 **1 real LLM call — running total:
5**) and probably exceeds the tiny budget on its own. Send a **second** message.
**You should see:** The second attempt is refused **before** any model call — a toast: *"This
agent's own monthly token budget ({used}/{limit} tokens) is exhausted."* with a **Go to
agent** action button.
**If it looks wrong:** this is a genuinely different failure from the *tenant-wide*
AI-credit quota (which shows *"Your workspace's AI-credit quota is exhausted for this billing
period."* with a **Go to Billing** button instead, landing on Team & Billing's Billing tab
directly) — both are real 402 responses, just two different gates with two different fixes.
You're unlikely to hit the tenant-wide one in a normal test run; the agent-level one above is
the one worth deliberately triggering.

**9.4 — A genuinely rejected file type.**
**Click:** In a channel (not 1:1 chat), try uploading a **PDF**.
**You should see, precisely:** the upload is **not** rejected for being a PDF at the file
level — `.pdf` is an allowed upload extension, and its text does get extracted. The real
rejection happens one step later, when the extracted file tries to register **as a data
source**: *"pdf has no working connector yet — its text can be extracted, but there's no
destination data model to sync or profile it into."* This is a real, deliberate 422 from the
backend, shown verbatim in the chat's upload-error area — not a generic "upload failed."
**If it looks wrong:** if the PDF appears to upload successfully with no error at all, that's
worth reporting — the rejection is supposed to happen at registration, every time.

💰 *Section running total after Section 9: 5 (assuming exactly one budget-exhaustion message
sent in 9.3; 9.1/9.2/9.4 cost nothing).*

---

## 10. Needs you, Scheduled

**10.1 — Needs You.**
**Click:** Sidebar → **Needs you** (badge shows a live count if anything's waiting).
**You should see:** Everything genuinely waiting on you, across every project, in one
tier-sorted list — the task you paused for approval in Section 5 (if you haven't resolved it
yet) would show here as an **approval** card with **Approve**/**Reject**/**Open task**
buttons; a task stuck from Section 9.1 would show as a **blocked** card with **Open task**/
**Start a new task**. If nothing's pending: *"Nothing needs you right now"* — a real, calm
empty state, not a broken screen.
**If it looks wrong:** the Sidebar's badge count and this page's own count should always
agree — they're now computed from the exact same derivation. If they ever disagree, that's
worth reporting.

**10.2 — Scheduled.**
**Click:** Sidebar → **Scheduled**.
**You should see:** A tenant-wide table — What / Agent / Project / Schedule / Last run / a
static **on**/**off** badge (no toggle switch — there's no manual pause, only automatic
deactivation) — of every `ScheduledAgentTask`, agent schedules only. Pipeline `schedule_cron`
is deliberately **not** shown here; it lives in each project's Workbench Pipelines tab
instead.
**If it looks wrong:** the list is almost certainly empty on a fresh account — **there is no
"New schedule" button anywhere in this UI today.** That's not an oversight to report; it's
Known Issue #100 below. Creating one requires a direct API call:
```bash
curl -X POST http://localhost:8000/api/v1/agents/{agent_id}/schedules \
  -H "Authorization: Bearer {your_token}" -H "Content-Type: application/json" \
  -d '{"task_shape":"sync_profile_quality","description":"Daily freshness check","tool_name":"sync_source","tool_args":{"source_id":"{a real source id}"},"schedule_cron":"0 8 * * *"}'
```
If you do seed one this way and it later auto-deactivates (e.g. because you deleted its
source), the real reason text appears verbatim on this page, with **Reactivate** (genuinely
re-validates live — if the cause is still true, it fails again right at the click, not
silently at the next 3am firing) and **Delete**.

💰 *No LLM calls in this section. Running total: 5.*

---

## 11. Offboarding, deleting a project

**11.1 — Offboard an agent.**
**Click:** `/agents/{id}` (any agent with no in-progress task) → **Danger zone** card →
**Offboard agent**.
**You should see:** A confirm modal — *"{name} will stop being reachable from chat, channels,
and new tasks. This can't be undone from this screen. If {name} has a task still in progress,
offboarding will be blocked until it's resolved."* Click **Offboard**.
**You should see:** A toast — `"{name}" has been offboarded.` — you're returned to `/agents`.
Revisiting this agent's page shows a persistent notice: *"This agent has been offboarded —
it can no longer be reached from chat, channels, or new tasks. Its history and source scope
are preserved."*
**If it looks wrong:** try this on an agent with a task still paused for approval first —
you should get a **blocked** response (409), not a silent success: a warning toast naming
the exact blocking task, with a **View task** action. A `PAUSED_NEEDS_APPROVAL` task counts
as "still in progress" here, same as a running one.

**11.2 — Delete a project.**
**Click:** `/projects` → the **⋮** menu on any project row (icon-only, no visible text
label) → **Delete**.
**You should see:** A confirm modal — *"This removes the **{name}** grouping. This can't be
undone."* — followed by a real, live-fetched sentence naming exactly what survives, e.g.
*"Nova and Atlas stay on your team and become unassigned. #warehouse-check stays."* Click
**Delete**.
**You should see:** A toast — `"{name}" deleted.` The project is gone from the list, but
check `/agents` — its agents are still there, just with no project. Any channel that
belonged to this project still exists too, just ungrouped.
**If it looks wrong:** unlike offboarding, there's **no** in-progress-work check here at
all — deleting a project never blocks on anything, by design (it's grouping metadata, not
something with its own execution to protect). That's not a bug if you can delete a project
with an active task still running inside it.

💰 *No LLM calls in this section. Running total: 5.*

---

## 12. Team, billing, settings, audit log

**12.1 — Team.**
**Click:** Sidebar → **Team & billing** (defaults to the **Team** tab).
**You should see:** A **Members** table and, if you're an Owner/Admin, a **Pending Invites**
table and a **+ Invite Member** button.

**12.2 — Billing.**
**Click:** The **Billing** tab on the same page.
**You should see:** **Current plan** card, a **Usage this month** card with real progress
bars (AI Credits, Pipeline Runs, Data Sources, Team Members — this is where your running LLM
spend from this whole walkthrough actually shows up as a number), and a **Checkout & invoices**
placeholder card (*"Coming soon"*).
**If it looks wrong:** go back and re-trigger the quota-exceeded toast from Section 9.3's
sibling (the tenant-wide one, not the agent one) if you want to confirm its **Go to Billing**
button lands you directly on this tab, not just on the Team page.

**12.3 — Settings.**
**Click:** Sidebar → **Settings**.
**You should see:** 7 tabs — **Workspace**, **Profile**, **Notifications**, **AI Model**,
**Theme**, **API Keys**, **Audit Log**.
- **AI Model** — a dropdown: *Use plan default* / *Gemini 3.5 Flash* / *GPT-OSS 120B (Groq)*.
  If you see "Llama 3.3 70B" listed here instead of GPT-OSS 120B, your build predates the
  2026-09-15 fix (Known Issue #102, closed) — that option used to save an override the
  backend silently ignored.
- **API Keys** — you can create one, but a note above the form says exactly what's true
  today: *"API keys are for reference and audit today — nothing in AXIOM currently accepts
  one as a request credential."*

**12.4 — Audit Log.**
**Click:** The **Audit Log** tab (last one).
**You should see:** Every governance/approval action taken in this workspace — actor, action
(e.g. `contract.created`), resource, timestamp. Everything you did in Sections 5, 6.8, and 11
should show up here.
**If it looks wrong:** this tab used to be split across a separate `/governance` page
(Contracts + Audit) and a dead `/audit` stub with no content of its own — both retired; if
you land on either old URL, you should get bounced here automatically with a toast explaining
why, not a 404.

💰 *No LLM calls in this section. Running total after the full walkthrough: 5* (or however
many extra chat/channel messages and tasks you actually sent along the way — this number is
a floor, not a ceiling; every real message and every "Generate Plan" click adds one more).

---

## Known Issues

Six things already known and tracked — check here before assuming a fresh discovery.
Full detail for all of these lives in `docs/context/WALKTHROUGH_FINDINGS_2026-08.md`.

- **#76 — A task denied on scope is permanently dead, even after the scope is granted.**
  (Section 9.1.) `PAUSED_FAILED_STEP` has no resume path for any cause — scope denial,
  attempt-budget exhaustion, or the initiating user losing access. The fix a denial message
  walks you through (grant the source) does not unblock *that* task — only a new one. Open.

- **#91 — `WorkspacePicker`'s "current workspace" row is unreadable in dark mode.** The
  always-disabled "current" option falls back to native disabled-button styling, which
  assumes a light background. Reachable from the sidebar's account-row "Switch workspace"
  flow on a real two-workspace account. Open.

- **#98 — Approving a task-linked approval through the generic `/approvals` endpoint runs the
  action but leaves the task stuck in `PAUSED_NEEDS_APPROVAL` forever.** A task's own paused-
  for-approval state and a standalone approval request can be the literal same underlying row;
  the generic approve path never tells the task about it. Needs You (Section 10.1) routes
  around this by construction — resolving from there is always safe — but the generic
  endpoint itself still has the gap if reached another way. Open.

- **#99 — The "Grant access" deep-link the design called for can't be built honestly yet.**
  (Section 9.1's denial message.) The structured `{agent_id, source_id}` data needed to build
  a precise link is computed once, used for a real-time Slack/email alert, and then thrown
  away rather than saved onto the task — so the task detail page and Needs You only ever see
  the flattened prose version, not the structure. The real fix is persisting what's already
  computed, not inventing new structure. Open.

- **#100 — There is no "New schedule" button anywhere in the UI.** (Section 10.2.) A
  schedule's `tool_args` shape differs per tool across roughly 14 schedulable tools with no
  single form-schema to render from — building this honestly means either hand-mapping every
  tool's real argument shape or exposing the same JSON schema the planner's own LLM prompt
  already uses. Until then, schedules are created via direct API call only (curl example in
  Section 10.2). Open.

- **#101 — A full Analytics backend sits unused behind the retired `/analytics` stub.**
  Not shown anywhere in this guide because there's no UI for it — but the backend
  (`overview`, `recent-runs`, `pipelines`, `quality`, `kpis`, `usage`) is real and tested;
  `/dashboard` already uses the overview endpoint, the rest has no consumer yet. Logged so
  it doesn't get silently forgotten. Open.

- **#102 — Settings' AI Model picker used to offer a dead model.** Closed 2026-09-15, same
  day as this guide. If your build is current, you won't see it — mentioned in Section 12.3
  only so you can tell a stale build from a fresh discovery.

- **#103 — The "Connect one" link on an empty source list still points at the retired
  `/sources` route.** (Sections 3.2 and 3.4.) Shows up both in the Hire an agent modal and on
  the agent detail page's own "Data source scope" card. Clicking it doesn't 404, it bounces
  you back out with a toast — a dead end dressed as a shortcut. Open.

---

*Screenshots are deliberately not included in this version — they'll be captured from a real
walkthrough of this guide rather than a pre-run, so what's documented is what a real person
actually saw, not a staged version of it.*
