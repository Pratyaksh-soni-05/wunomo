# AXIOM Self-Test Guide — Try The Whole Product Yourself

This assumes you've never clicked through this product end to end, and
specifically that you've **never used the Tasks feature** — every click,
every field, every button label is spelled out exactly as it appears on
screen. If a step says "click **+ New Pipeline**," that's the literal text
you're looking for.

Work through the sections in order: **1. Pre-flight** gets everything
running, **2. Setup** gets one real file of data into the product, **3. The
full flow** is the main walkthrough (source → pipeline → quality rule →
the Tasks feature, start to finish), **4. What to try breaking** is a short
list of things worth deliberately doing wrong, and **5. LLM budget** tells
you what each part actually costs so you don't run out of AI calls halfway
through.

**Sections 6–14 are a later addition** (screens that had zero coverage
before) — do **6 (Dashboard)** right after your first login, before
Section 2; do **7–11** (Incidents, Transforms, Settings, Approvals,
Governance) whenever you like, ideally after you finish Section 3's Tasks
walkthrough since a couple of asides in Section 3 point forward to them;
**12** is a 5-minute sweep of the app chrome (sidebar, topbar, command
palette); **13 and 14 are reference, not steps** — read them, don't click
through them. Honestly, all of it together runs well past 90 minutes
(more like 2–2.5 hours) — if you're short on time, see the "fast path"
note at the top of Section 13.

---

## 1. PRE-FLIGHT — start everything and confirm it's healthy

### 1.1 Start Docker

Open a terminal (PowerShell — click the Windows Start button, type
`powershell`, press Enter) and run:

```
cd "C:\Pratyaksh Personal\My Projects\ai workforce\dataops-agent"
docker compose ps
```

**What you should see:** a table listing 5 rows — `dataops_backend`,
`dataops_beat`, `dataops_celery`, `dataops_postgres`, `dataops_redis` —
each with a `STATUS` column saying **`Up ...`**.

**If the table is empty, or any row doesn't say `Up`:**
```
docker compose up -d
```
Wait about 15 seconds, then run `docker compose ps` again and confirm all
5 rows say `Up`.

### 1.2 Confirm the backend is actually healthy (not just "the container started")

A container can say `Up` while the app inside it is still crashing. Check
the real thing:

```
curl http://localhost:8000/health
```
**Good result:** `{"status":"ok","env":"development","version":"1.0.0"}`

```
curl http://localhost:8000/health/db
```
**Good result:** `{"status":"ok","db":"connected"}`

**If either one fails to connect at all:** the backend container isn't
actually up yet — wait 10 more seconds and try again. **If `/health/db`
returns an error body** (not a connection failure, an actual error
message): Postgres isn't reachable — run `docker compose ps` again and
confirm `dataops_postgres` says `Up`.

### 1.3 Start the frontend

The frontend is *not* one of the Docker containers — you run it yourself,
in its own terminal window that has to stay open:

```
cd "C:\Pratyaksh Personal\My Projects\ai workforce\dataops-agent\frontend"
npm run dev
```

**What you should see:** after a few seconds, a line saying `Ready in
...ms`, and the window stays open (don't close it — closing it stops the
site). Leave this terminal running for your whole session.

Now open a browser and go to **http://localhost:3000**. You should land on
a login page. If the browser can't connect at all, the frontend isn't
actually up yet — check the terminal for a red error instead of `Ready`.

### 1.4 Which login to use

You have two options. **For this guide, use option A** — it gives you a
completely clean, empty account you fully control, which is what the rest
of this guide assumes.

**Option A — Sign up fresh (recommended for this guide).** On the login
page, click **Sign up** (a link near the bottom of the form). You'll fill
in your own email/password in step 3.1 below — don't do it yet, just
confirm the page loads.

**Option B — Use the pre-built demo account**, if you just want to look
around without setting anything up yourself:
- Email: `demo@axiom-yc.ai`
- Password: `AxiomDemo2026!`

This account already has a real source, a real pipeline with real run
history, and one real open incident — but it has **no Tasks data**, since
the Tasks feature didn't exist when this demo account was built. If you
use this login, you can skip straight to the Tasks part of Section 3
(3.9 onward), since the source/pipeline/quality-rule setup is already
done for you.

### 1.5 How to reset the demo account back to its known-good state

If you (or anyone else) has been clicking around in the demo account and
you want it back to exactly its original state:

```
cd "C:\Pratyaksh Personal\My Projects\ai workforce"
node dataops-agent/scripts/demo_reset.mjs
```

This takes 15–30 seconds and is safe to re-run any number of times — it
always rebuilds the same fixed state (one healthy pipeline, one broken
pipeline with one real open incident about it). It does **not** touch
your own fresh-signup account from Option A — that's a separate,
independent tenant. If you want to start *your own* account over, the
simplest way is just to sign up again with a new email — every signup
creates a brand new, empty account with nothing shared between accounts.

### 1.6 Check your AI quota before you spend any of it

This product uses two real AI providers (Google Gemini and Groq/Llama).
Both have a real daily limit, and this project's Gemini key is capped at
roughly **20 real requests per day** — not a lot. Section 5 below has the
full cost breakdown; this step is just about checking where you stand
*before* you start.

**Free check (costs nothing, just looks at what's already happened
today):**
```
docker exec dataops_postgres psql -U dataops_user -d dataops -c "SELECT provider, count(*) AS calls_today FROM llm_usage_events WHERE created_at >= CURRENT_DATE GROUP BY provider;"
```
This shows how many real AI calls have already happened today, split by
provider. If you see `gemini` already sitting near 20, expect it to fall
back to the other provider (Groq) automatically — the product handles
that on its own, you don't need to do anything.

**Optional live probe (costs exactly 1 real call, confirms the AI is
actually responding right now, not just that quota exists):**
```
node "C:\Pratyaksh Personal\My Projects\ai workforce\dataops-agent\scripts\demo_chat_test.mjs" "Say OK."
```
**Good result:** a line saying `status: 200`, a `provider:` name, and a
real reply from AXIOM within about 10 seconds. **Bad result:** `status:
500`, or it hangs for 30+ seconds. That means both providers are
temporarily unavailable — wait 15 minutes and try again; it's not
something you broke.

### 1.7 A closer look at the login screen

You've already glanced at this page in 1.3/1.4 — this is the full tour of
every control on it, field labels exactly as they appear in the code, not
paraphrased. You don't need to click through all of this now if you're
about to sign up (3.1) or use the demo login (1.4B) — this is here so you
know what every button on this screen actually does when you come back to
it later (e.g. logging back in, or logging in as the Viewer in §4.4).

**The default view (password login):**
- Input **Email**
- Input **Password**
- Button **Log in**
- Link-button **Email me a code instead** — switches to a passwordless
  flow: an **Email** field and a **Send code** button; after sending, a
  **Code** field (6 digits) and **Verify & log in** button, with
  **Resend code** (becomes **Resend in 60s** immediately after sending,
  counting down) and **Back to password**.
- Below the form: a divider reading **or**, then button **Continue with
  Google** — this genuinely redirects to Google's real OAuth consent
  screen; only follow it if you actually have a Google account you want
  to test with, this guide doesn't walk through that flow further.
- Footer: **Don't have a workspace? Sign up**

**If the email you log in with is linked to more than one workspace**
(this can happen if you signed up twice with the same email — see the
signup nudge below): a modal titled **Choose a workspace** appears, body
text *"This email is linked to more than one workspace. Pick which one to
continue into."*, with one clickable card per workspace showing its name.

**Worth knowing, not something to test directly:** if you land back here
with a URL ending in `?expired=1` (your session token aged out — JWTs on
this app last 60 minutes), you'll see a toast: *"Session expired — please
log in again."*

**On the signup side** (`Sign up` link, or directly typing your details in
§3.1): if you register with an email that already has a workspace, you
aren't blocked — a banner appears: *"Heads up — this email already has a
workspace (or N workspaces) (names…). Your new workspace was still
created."* with a button **Continue to your new workspace** and a link
**Log in to an existing workspace instead**. Worth trying once if you ever
sign up a second time in this guide (e.g. testing the Team invite flow's
own account creation) — otherwise not essential.

---

## 2. SETUP — get one real file of data into the product

### 2.1 The sample file

Save this as `sales_data.csv` anywhere on your computer (Desktop is fine —
you'll pick it from a file browser in a moment). This exact file already
exists at the root of this project too, at
`C:\Pratyaksh Personal\My Projects\ai workforce\sales_data.csv`, so you
can use that one directly instead of retyping it if you'd rather.

```csv
order_id,customer_name,product,quantity,price,date,status
1001,Rahul Sharma,Laptop,2,45000,2024-01-15,completed
1002,Priya Singh,Mouse,5,800,2024-01-16,completed
1003,Amit Kumar,Keyboard,3,1500,2024-01-16,pending
1004,Sneha Patel,Monitor,1,12000,2024-01-17,completed
1005,Raj Verma,Laptop,1,45000,2024-01-17,cancelled
1006,Deepa Nair,Headphones,4,2500,2024-01-18,completed
1007,Vikram Joshi,Mouse,2,800,2024-01-18,pending
1008,,Keyboard,1,1500,2024-01-19,completed
1009,Anita Desai,Monitor,2,12000,2024-01-19,completed
1010,Karan Mehta,Laptop,1,45000,2024-01-20,completed
```

Notice row `1008` has a **blank customer name** — that's deliberate. You'll
use it later to see a quality check genuinely catch something real,
instead of a check that just always passes and proves nothing.

### 2.2 Upload it as a Data Source

*(As of 2026-08-19: Data Sources, Data Catalog, Pipelines, Transforms,
Quality, Incidents, Governance, Automations, and CI/CD all live inside
**AXIOM's own sidebar domain** now, not the default Workspace sidebar you
land on after login — the same domain Chat and Tasks already used. To get
there: click **AI Employees** in the sidebar, then click into **AXIOM**'s
card (or just navigate to any of those screens directly — the first click
into one of them swaps the sidebar automatically). A **← Back to
Workspace** link appears at the top of the sidebar the whole time you're
in this domain, replacing the **Production** row. Once you're in, all of
the screens above stay in the same sidebar together — you won't need to
repeat this for Pipelines/Quality right after Data Sources. Approvals
stayed in the regular Workspace sidebar — it's not part of this domain.)*

1. Click **AI Employees** in the sidebar, then click into **AXIOM**'s
   card. In the sidebar that appears, click **Data Sources**.
2. Click **+ Add Source** (top right).
3. A window titled **Add Data Source** opens. The **Type** dropdown
   already says **CSV file** — leave it as is.
4. Click the **File** field and pick `sales_data.csv` from your computer.
5. A **Name** field appears, pre-filled with the filename. Clear it and
   type: `Sales Orders`
6. Click **Upload & Create** (bottom right of the window).

**What you should see:** a green success message near the bottom of the
screen, the window closes, and a new row appears in the table: **Sales
Orders**, type `csv`, status **Active**, and a **Last Profiled** column
that says **Never**.

### 2.3 Confirm it actually profiled — this is the step people miss

Uploading a file registers it, but it does **not** automatically read its
column structure — you have to ask it to, once, per source.

1. On the **Sales Orders** row, click **Profile**.
2. Wait a couple of seconds.

**What you should see:** a green "Source profiled" message, and the
**Last Profiled** column now shows a real date/time instead of "Never."

**If it looks wrong** (still says "Never" after clicking Profile, or an
error toast appears): click **Profile** again — this action is safe to
repeat. If it keeps failing, re-check Section 1.2 (backend health) — a
profile failure almost always means the backend lost its connection to
the uploaded file, which usually means Docker was restarted without the
upload volume attached.

*(Optional double-check: click* **Data Catalog** *in the sidebar — you
should see* **Sales Orders** *listed with 7 real columns:* `order_id`,
`customer_name`, `product`, `quantity`, `price`, `date`, `status`*.)*

### 2.4 Also try on this screen (optional, any time after 2.3)

Two more row actions exist on Data Sources that the walkthrough above
doesn't use:

- **Sync** — re-reads the source's data (for a CSV, effectively a no-op
  refresh since the file doesn't change; this matters more for a database
  source). Click it on the **Sales Orders** row. **What you should see:**
  a "Sync started." toast. No AI cost — this is a plain data operation.
- **Delete** — removes the source. **Don't do this on Sales Orders** — the
  rest of this guide depends on it existing. If you want to see the
  delete flow, upload a disposable second source first (repeat 2.2 with
  any small file, or even the same `sales_data.csv` under a different
  name), then delete *that* one.

### 2.5 Your quota headroom for this specific walkthrough

One thing that would normally be worth testing deliberately — what
happens when a tenant's AI-credit quota actually runs out (a real `402`
response, the product's own quota-wall) — **isn't reachable in this
walkthrough, and that's expected, not a gap.** `demo_reset.mjs` (§1.5) sets
the demo tenant's plan to `scale` (500,000 AI credits/month) specifically
so rehearsals don't hit a quota wall. If you're on your own fresh-signup
account instead (§1.4A), you're on whatever the default starter plan's
credit allowance is — still generous enough that this guide's handful of
real AI calls (see Section 5) won't come close to it. Either way: **if you
don't see a 402/quota-exceeded message anywhere in this guide, that's the
scale plan (or a healthy starter allowance) doing its job, not something
missing.**

---

## 3. THE FULL FLOW — one numbered step per click

### Part A — Source → Pipeline → Run

**3.1** *(Skip this if you're using the demo login from 1.4B.)* If you
haven't signed up yet: on the login page, click **Sign up**. Fill in:
- **Full name**: anything, e.g. `Test User`
- **Email**: any email you haven't used before, e.g. `test1@example.com`
- **Workspace name**: anything, e.g. `My Test Company`
- **Password**: anything 8+ characters

Click **Create account**.

**What you should see:** a short 4-step onboarding wizard (pick anything
in each step — role, industry, company size, use cases — none of it
affects this test). Click through it with **Next**, then **Finish** on
the last step. You land on the **Dashboard**.

*(Section 6 below is a full tour of this Dashboard screen — worth doing
right now, before you go further, since you're already looking at it.)*

**3.2** If you already did Section 2 (uploaded Sales Orders), skip ahead
to 3.3. Otherwise, go do Section 2 now, then come back here.

**3.3** In the left sidebar, click **Pipelines**.

**3.4** Click **+ New Pipeline** (top right).

**3.5** In the window that opens:
- **Name**: type `Sales Ingestion Pipeline`
- **Source**: open the dropdown and pick **Sales Orders**
- **Description**: type `Pulls in sales orders` (optional, but type it
  anyway so you can see the field work)
- **Schedule (cron, optional)**: leave blank — you'll run it manually

Click **Create**.

**What you should see:** the window closes, a green success message
appears, and **Sales Ingestion Pipeline** appears in the table with status
**draft** and "Never run" under Next/Last Run.

**3.6** On that row, click **Trigger**.

**What you should see:** a "Run triggered" message. Within a couple of
seconds (refresh isn't automatic here — click **Trigger** once and wait,
or click the pipeline's name to check), the row's **Next / Last Run**
column should show **Last: success** in a green badge.

**If it shows a red "failed" badge instead:** click the pipeline's own
**name** (it's a clickable link) — a window titled **Runs — Sales
Ingestion Pipeline** opens showing every run with a real error message.
The most common cause at this stage is the file upload not being visible
to the pipeline worker — re-check that Section 2.3's Profile step
actually succeeded.

**3.7** Click the pipeline's name (**Sales Ingestion Pipeline**) to open
its run history.

**What you should see:** a window listing at least one run, status
**success**, with a real row count (10 — matching the 10 data rows in the
CSV) and a real duration in milliseconds. Close the window (click outside
it or the X).

*Also try on this screen (optional, any time after this step):* each row
has **Trigger**, then either **Activate** (if the pipeline is currently
`paused`) or **Pause** (if it's active), and **Delete**. Click **Pause** —
the badge should flip to `paused` and a "Pipeline paused." toast appears;
click the same button (now labeled **Activate**) to flip it back. Don't
**Delete** this pipeline — Part B and Part C both depend on it.

### Part B — A quality rule that actually catches something

**3.8** In the left sidebar, click **Quality**.

**3.9** Click **+ New Rule**.

**3.10** In the window:
- **Name**: `No missing customer name`
- **Pipeline**: pick **Sales Ingestion Pipeline**
- **Rule type**: leave it on **not_null** (the first option)
- **Column (optional)**: type `customer_name`
- **Severity**: leave on the default

Click **Create**.

**3.11** On the new rule's row, click **Run Checks**.

**What you should see:** a message like "Checks ran — score ..., X
passed / 1 failed." — the **1 failed** is real: it's catching row 1008's
blank customer name. The **Pass / Fail** column on that row should now
show real numbers, not `0 / 0`.

*(One thing worth knowing: "Run Checks" re-runs* **every** *quality rule
attached to that pipeline, not just the one you clicked it on — if you
add more rules later, all of them run together.)*

*Also try on this screen (optional):* each row also has a **Delete**
button — click it on a disposable rule if you want to see the flow (a
"Rule deleted." toast, and the row disappears). Don't delete **No missing
customer name** if you want to keep re-running it later.

### Part C — The Tasks feature (this is the new part)

This is where AXIOM actually plans and does multi-step work on its own,
with you reviewing and approving each risky step before it happens.
Nothing you've done so far in this guide used AXIOM's AI at all — this is
the first part that spends real AI calls (see Section 5 for exact costs).

**3.12** In the left sidebar, under **WORKSPACE**, click **AI Employees**.

**What you should see:** a grid of AI employee cards — **AXIOM** is the
only one marked **Active**; the rest (LEDGER, DEPLOY, INSIGHT, SENTINEL,
PULSE) are labeled **Coming Soon** and have no button. On the AXIOM card,
click **Open AXIOM →**.

**What you should see now:** you land on the chat screen, and the sidebar
itself changes — the full workspace nav list crossfades out and is
replaced by **AXIOM** (with its **Live** badge), **Tasks**, and (as of
2026-08-19) the full set of DataOps operational screens too: **Data
Sources**, **Data Catalog**, **Pipelines**, **Transforms**, **Quality**,
**Incidents**, **Governance**, **Automations**, and **CI/CD** — this is
the same expanded list §2.2 already had you click into for Data Sources,
if you did Section 2 first. At the top of the sidebar, where
**Production** used to sit, a **← Back to Workspace** link now appears —
that's your way out of AXIOM's domain from anywhere inside it, not just
from this screen. Approvals stays in the regular Workspace sidebar, not
here. (This is a 2026-08 change — AXIOM used to be a direct top-level
sidebar item; it's now nested behind AI Employees like every other AI
employee will be, and as of 2026-08-19 covers the operational screens
above too, not just chat and Tasks.)

![AXIOM chat screen with the "+ Start a Task" button](self_test_assets/01-chat-start-task-button.png)

**3.13** In the top right of the chat panel, click **+ Start a Task**.

**What you should see:** a window titled **Start a Task** opens, with a
text box labeled **"What should AXIOM do?"** and a dropdown labeled
**"Task type."**

![The Start a Task modal](self_test_assets/02-start-a-task-modal.png)

**3.14** In the text box, type exactly:
```
Check the health and recent run history of my Sales Ingestion Pipeline.
```

**3.15** Leave the **Task type** dropdown on its default value,
**"Diagnose pipeline failure."**

**3.16** Click **Generate Plan** (bottom right).

**Cost: 1 real AI call** (occasionally 2 — see Section 5 for when and
why; never more than 2).

**What you should see:** the button changes to "Generating plan…" for a
few seconds (this is a real AI call happening) — then a green "Plan
generated — review it before approving" message, and a new card appears
right in the chat: **"Started task: Check the health and recent run
history of my Sales Ingestion Pipeline."** with a **View progress**
button.

![The inline "Started task" card in the chat thread](self_test_assets/03-task-card-in-chat.png)

**If nothing happens after 30+ seconds, or you see a red error message:**
the AI provider is likely temporarily unavailable — this is the same
"bad result" case from the 1.6 quota check. Wait a few minutes and try
again with the **+ Start a Task** button; nothing was created (check the
**Tasks** page — it should be empty if this happened).

**3.17** Click **View progress** on that card.

**What you should see:** you're taken to a new page. At the top: the goal
you typed as the title, a light-blue **Draft Plan** badge, and a real
step-by-step plan in a table — showing exactly which tool AXIOM plans to
call and with what arguments (this is real, not a guess — it's what will
actually run if you approve it).

![The plan review screen showing real steps and tool arguments](self_test_assets/04-draft-plan-review.png)

*Your exact plan might have a different number of steps than the
screenshot — that's normal, AXIOM generates it fresh from a real AI call
each time.*

**3.18** Now let's edit a step, to see AXIOM tell the difference between
what it planned and what a human changed. Click **Edit Plan** (top right
of the plan card).

**3.19** The first step's description becomes an editable text box. Click
into it, clear it, and type:
```
Check the pipeline's recent runs (edited by a human reviewer).
```

**What you should see, while still in edit mode:** below the description,
each step also has editable **Tool name** and **Tool args** fields — the
latter a free-text JSON box. You don't need to touch these for this
walkthrough, but it's worth knowing they're there: this box does **not**
validate the JSON as you type — if you type something that isn't valid
JSON, it's silently ignored (your last valid value is kept) with **no
visible error message**. If you want to see this for yourself: click into
a step's tool-args box, type a stray `{` with nothing else, then click
elsewhere — nothing will look wrong, but your edit didn't take. Not a bug
worth reporting; it's on the known-issues list (Section 14).

**3.20** Click **Save Changes**.

**What you should see:** a "Plan updated." message, the task-level badge
row now shows an extra orange **Plan edited** badge, and — the important
part — the step's **Origin** column, which said gray **"AXIOM planned"**
before, now says orange **"Human edited."**

![After editing: the step's origin badge changed to "Human edited"](self_test_assets/05-edited-step-human-badge.png)

*(If you want to back out of an edit instead of saving it: while in edit
mode, a* **Discard edits** *button sits next to* **Save Changes** *— it
drops whatever you typed and returns to the read-only plan view with
nothing changed.)*

**3.21** Click **Approve Plan** (bottom right of the card).

**What you should see:** the status badge flips from **Draft Plan** to
**Queued**, the Edit/Approve/Reject buttons disappear, and two new
buttons appear at the top right: **Advance one step** and **Run to
completion**.

**3.22** Click **Run to completion**.

**Cost: 0 real AI calls, normally.** The one exception: if a step's tool
call comes back with a real, structured error (e.g. "pipeline not
found"), AXIOM gets **exactly one** extra AI call for *that step* to try
adapting its arguments before giving up — capped at 1 extra call per step
no matter how many of its retries happen. Whether this fires depends on
what AXIOM's plan actually contains, which is why it isn't a guaranteed
cost.

**What you should see:** the button changes to "Running…" and the step
timeline below updates live as each step actually runs. Wait for it to
settle (a few seconds per step). It will land on one of these real, valid
outcomes — **all of these are correct, normal results**, not bugs:

- **Completed** (green badge) — every step succeeded. The step timeline
  shows a green "succeeded" status and a real outcome summary for each
  one.
- **Paused Failed Step** (orange badge) — a step tried something (like
  looking up the pipeline by the exact name AXIOM guessed) and it didn't
  resolve after 3 real attempts. A banner at the top will name the exact
  step and the exact error — read it, it's specific, not generic.

Either way, the **step_budget** counter near the top ("N/20 steps used")
should have gone up from `0/20`, and the top-right topbar's "N active"
counter (next to the calendar icon) should reflect it.

![An example terminal state — a real failed step with a specific reason](self_test_assets/08-terminal-state-example.png)

**3.23** Click **← All tasks** (top left) to go back to the list.

**What you should see:** a table with the one task you just ran, showing
its real final status, whether the plan was edited, and when it was
created.

![The Tasks list page](self_test_assets/09-tasks-list.png)

*(Optional — a second way to reach this whole flow: the exact same
"Start a Task" modal is also reachable directly from this Tasks list
page — click* **+ New Task** *at the top right, or, if the list is empty,
the identical button inside the empty state. It's the literal same
component "+ Start a Task" in chat opens; nothing behaves differently
depending on which entry point you used.)*

### Part D — Hitting an approval gate (AXIOM asking permission)

Some actions are riskier than just *looking at* things — syncing a real
data source, for example. AXIOM is required to pause and ask a human
before doing those, no matter what. Let's trigger that on purpose.

**3.24** Go back to **AXIOM** in the sidebar, click **+ Start a Task**
again.

**3.25** In the text box, type:
```
Sync and profile my Sales Orders source, then run quality checks on it.
```

**3.26** Open the **Task type** dropdown and pick **"Sync, profile &
quality-check a source."**

**3.27** Click **Generate Plan**, then click **View progress** on the new
chat card, same as before.

**Cost: 1 real AI call** (occasionally 2, same rule as 3.16).

**3.28** Review the plan (same as 3.17 — no need to edit this one), then
click **Approve Plan**.

**3.29** Click **Run to completion**.

**What you should see:** it runs for a moment, then **stops itself** with
a new status badge: **Paused Needs Approval**. A banner explains exactly
which step is waiting and which real action it wants to run (something
like `sync_source`). Below that, a card titled **"Approve or reject this
step"** appears, with an optional notes field and two buttons: **Reject
Step** and **Approve & Resume**.

![The approval gate — AXIOM stopped and is asking for a decision](self_test_assets/06-approval-gate.png)

*(Optional, zero extra cost, and a good moment to do it: before you click
anything below, open a second browser tab to* **Approvals** *in the
sidebar. You should see this exact pending action listed there too — same
underlying data, a different screen. Section 10 covers that screen in
full; this is the one point in the guide where it'll actually have
something real in it without you having to manufacture a second approval
just to see it populated.)*

**3.30** Click **Approve & Resume**.

**What you should see:** a "Step approved — resuming." message. The
status flips back to **Running**, and the step's row in the timeline now
shows **succeeded** with a real outcome (e.g. real row counts from the
sync). The **Advance one step** / **Run to completion** buttons come back.

![After approving — the step ran for real and succeeded](self_test_assets/07-after-approve-and-resume.png)

**3.31** Click **Run to completion** again.

**What you should see:** this plan has more than one step that needs
approval (`sync_source`, `profile_schema`, and `run_quality_checks` are
all in this "riskier" category) — so it will likely **pause again**,
asking for approval a second (or third) time. That's expected, not a
bug. **Repeat step 3.30** (click **Approve & Resume**) each time it
pauses, until it reaches a final state (Completed, Completed With
Unconfirmed Steps, or Paused Failed Step). Every pause is real — you're
approving one genuinely new action each time, not clicking through the
same thing twice.

You've now seen the entire arc the Tasks feature is built around: a real
plan, a human edit, approval, real execution, a real safety stop, and a
real resume.

**3.32** *(Optional — seeing the other half of an approval decision.)*
Everything above showed you **Approve & Resume**. To see its sibling:
start one more small task (repeat 3.24–3.28 with the same
"Sync, profile & quality-check" goal/type — this costs one more AI call,
see Section 5), and when it pauses on **Paused Needs Approval** this time,
type anything into the optional notes field (e.g. `Not needed right now`)
and click **Reject Step** instead of Approve & Resume.

**What you should see:** the step is marked rejected with your notes
attached, and the task does not proceed past that point — it does not
silently continue as if nothing happened. This is the deliberate opposite
of 3.30: a real "no," not just a real "yes."

---

## 4. WHAT TO TRY BREAKING

These are things a real user does by accident (or on purpose) that are
worth deliberately testing. None of these should crash the app or show a
blank white screen — if any of them do, that's a real bug worth writing
down.

### 4.1 Start a task with a vague, useless goal

Click **+ Start a Task**, type just: `help` — leave the type on
**"Diagnose pipeline failure"** — click **Generate Plan**.

**Cost: 1 real AI call** (occasionally 2, same rule as 3.16) — only if
you actually do this optional test.

**Two valid outcomes**, both fine:
- A red error message appears saying it couldn't generate a valid plan.
  Check the **Tasks** list — nothing new should be there (a failed
  generation never creates a task).
- AXIOM generates *some* real plan anyway, even though your goal was
  vague — AI models generally try their best rather than refusing. If
  this happens, open it and just click **Reject Plan** (see 4.2) instead
  of approving something you didn't really want.

### 4.2 Reject a plan

Start any small task (e.g. type `Check system health` with type
**"Diagnose pipeline failure"**). On the plan review screen, click
**Reject Plan** (red button, bottom right — it fires immediately, no
"are you sure" prompt).

**What you should see:** a message: "Plan rejected. Start a new task to
try again." The status badge changes to **Plan Rejected**, and there are
no more action buttons on the page — it's a dead end by design. You'd
need to start a brand new task to try again, which the message tells you
directly.

### 4.3 Cancel a task mid-run

Start a task, approve its plan (so it's in **Queued** or **Running**
status), then — before it finishes — click **Cancel Task** (top right,
red button, visible whenever a task isn't already finished).

**What you should see:** the status flips to **Cancelled**, and a banner
explains who cancelled it. If a step happened to be actively running at
that exact moment, the banner will say so honestly — it can't interrupt a
step that's already mid-flight, but it guarantees the task's overall
status stays **Cancelled** no matter what that step ends up doing.

### 4.4 Run a task as a Viewer (the interesting one)

This tests something specific: **a Viewer can create and approve a task
plan just fine — the block only happens when a step actually tries to
run**, because AXIOM re-checks your real permissions right before each
action, not just once at the start.

**Set up a Viewer account** (only needs doing once):
1. In the sidebar, under **ADMIN**, click **Team**.
2. Click **+ Invite Member**.
3. **Email**: type anything, e.g. `viewer-test@example.com` (it doesn't
   need to be a real, reachable email — you'll use the link directly).
4. **Role**: open the dropdown and pick **Viewer**.
5. Click **Send Invite**.
6. **Important — copy this now, you only get to see it once:** a box
   appears with a real link starting with
   `http://localhost:3000/invite/accept?token=...`. Select all of it and
   copy it before doing anything else. Click **Done** only after you've
   copied it.

**Accept the invite as the Viewer** — **use a Private/Incognito browser
window for this part** (Ctrl+Shift+N in Chrome/Edge), not just a new tab.
Using a regular new tab will log you out of your own account, because
both tabs share the same login storage.
1. In the Incognito window, paste the invite link and press Enter.
2. You'll see "You've been invited to join ... as viewer." The **Email**
   field is locked to what you typed. Type a **Full name** (optional) and
   a **Password**.
3. Click **Accept invite & join**.

**Now, still in that Incognito window, as the Viewer:**
1. In the sidebar, click **AI Employees**, then on the AXIOM card click
   **Open AXIOM →** (same detour as §3.12 — the Viewer lands on the
   dashboard fresh, so AXIOM isn't in their sidebar until they go through
   AI Employees either, same as anyone else).
2. Click **+ Start a Task**.
3. Type: `Sync and profile my Sales Orders source, then run quality checks on it.`
4. Pick task type **"Sync, profile & quality-check a source."**
5. Click **Generate Plan**, then **View progress**.

**Cost: 1 real AI call** (occasionally 2, same rule as 3.16) — this comes
out of the same shared daily quota as everything else in this guide, not
a separate per-user allowance.

**What you should see:** this all works completely normally — a Viewer
can create a plan, edit it, and approve it, exactly like before.

6. Click **Approve Plan**, then **Run to completion**.

**What you should see now — the real point of this test:** the first
step that tries to actually *do* something (like `sync_source`) fails
immediately, landing on **Paused Failed Step**. The banner will say
something like *"Blocked: the initiating user's role ('viewer') no
longer has permission to use 'sync_source'."* — a real, specific
permission block, caught at the moment of execution, not before. This is
intentional: **creating and approving a plan is always allowed; running
it is checked fresh, every single step.**

### 4.5 Two endpoints with no permission check at all (backend-only, not clickable)

Everything above is AXIOM correctly *blocking* a Viewer. These two are the
opposite: two real backend endpoints that have **no role check whatsoever**
— reachable by a Viewer (or anyone authenticated) exactly as freely as an
Owner. Neither has a button anywhere in the UI that calls it — the only
way to exercise them is a direct API call, so this one's for your browser
devtools or a terminal, not a click path. Still in that same Incognito
(Viewer) window from 4.4:

1. Open browser devtools (F12) → **Console** tab.
2. Run: `localStorage.getItem("axiom_token")` and copy the string it
   returns (no quotes) — that's the Viewer's real JWT.
3. In a terminal, with that token substituted in:
```
curl -X POST http://localhost:8000/api/v1/governance/lineage/nodes \
  -H "Authorization: Bearer <paste the Viewer token here>" \
  -H "Content-Type: application/json" \
  -d "{\"node_type\": \"source\", \"name\": \"viewer-test-node\"}"
```

**What you should see:** a real `200`/`201` success response, not a `403`
— a Viewer creating governance lineage data, which nothing in the role
system currently stops. (The matching `POST
/api/v1/governance/lineage/edges` has the identical gap, if you want to
try that one too.)

4. Also try the plain upload endpoint (distinct from the "Add Data
   Source" modal, which correctly uses a different, gated endpoint):
```
curl -X POST http://localhost:8000/api/v1/uploads/ \
  -H "Authorization: Bearer <paste the Viewer token here>" \
  -F "file=@C:\Pratyaksh Personal\My Projects\ai workforce\sales_data.csv"
```

**What you should see:** also a real success response — this one parses
and previews the file (it doesn't register a permanent Data Source, so
it's lower-stakes), but a Viewer reaching it at all is inconsistent with
AXIOM's own equivalent tool (`ingest_file`), which *does* require
operator-level permission.

Neither of these is dangerous by itself in this dev environment — flagged
here so you know what you're looking at if you notice it, not because
either one does real damage on its own.

---

## 5. LLM BUDGET — what costs a real AI call, and what doesn't

Two things drive real cost in this product: **sending a chat message**,
and **generating a task plan** (Section 8 adds two more: generating a
transform, and asking AXIOM to explain one). Almost everything else —
approving, editing, cancelling, viewing — is free (a plain database
action, no AI involved).

| Action | Real AI calls it costs |
|---|---|
| Uploading/profiling a source | 0 |
| Creating/triggering a pipeline | 0 |
| Creating/running a quality rule | 0 |
| Sending one message in AXIOM chat | **1** |
| Clicking "Generate Plan" for a new task | **1** |
| Editing a plan's steps | 0 |
| Approving or rejecting a plan | 0 |
| Advance one step / Run to completion | 0, **unless** a step hits a real error (e.g. "not found") — then **1 extra call** for that one step, to try correcting itself. Capped at 1 extra call per step, no matter how many of its 3 retry attempts happen. |
| Approve & Resume on a paused step | 0 — confirmed: resuming a step never calls the AI at all |
| Rejecting a step | 0 |
| Cancelling a task | 0 |
| Transforms: Generate (Natural Language tab) | **1** |
| Transforms: Explain (Python tab) | **1** |
| Transforms: Dry Run / Execute / Preview / Replay | 0 — these run real code, they don't call the LLM |

### 5.1 A ledger, so you can total your own path through this guide

Not every step above is something you'll necessarily do (several are
marked optional), so here's every *possible* AI-costing step in this
guide, in the order you'd hit them, so you can add up whichever ones you
actually did:

| Where | What | Cost |
|---|---|---|
| §3.16 | Generate Plan — diagnose pipeline failure | 1 (rarely 2) |
| §3.22/3.31 | Any step that hits a real domain error during execution | +1 per such step (capped, not guaranteed) |
| §3.26 | Generate Plan — sync/profile/quality | 1 (rarely 2) |
| §3.32 *(optional)* | Generate Plan — second sync/profile/quality task, for the Reject Step test | 1 (rarely 2) |
| §4.1 *(optional)* | Generate Plan — vague goal test | 1 (rarely 2) |
| §4.4 | Generate Plan — as the Viewer | 1 (rarely 2) |
| §8.2 | Transforms: Generate (NL tab) | 1 |
| §8.4 | Transforms: Explain (Python tab) | 1 |

**Required path (skip every step marked optional, no self-correction
retries fire):** 5 real calls. **Doing literally everything in this
guide, including every optional test, with no retries:** 7 real calls.
**Worst realistic case** (a couple of steps happen to hit a domain error
and self-correct, plus a plan generation or two needs its one corrective
retry): somewhere in the 9–12 range. All of these comfortably fit inside
a fresh day's ~20-call Gemini budget, before Groq (the second provider,
much larger shared pool) ever needs to back it up.

**If you do run out:** the product automatically switches to the second
AI provider (Groq) on its own — you don't have to do anything, and you
won't necessarily notice, since both produce real answers. You can see
which one handled any given task by checking the real `provider` field —
the chat screen shows "Ready · last reply via gemini" (or `groq`) right
under AXIOM's name at the top of the chat panel. If *both* providers are
exhausted at the same time (rare, but possible on a busy day), you'll see
a clear inline error message in the chat instead of a hang or a crash —
wait a while and try again.

---

## 6. THE DASHBOARD — your first stop after login

*(~5 minutes. Best done right after 3.1, since you land here automatically
after signup/onboarding — but works fine any time, from any account.)*

Click **Dashboard** in the sidebar (top item, no section label above it)
if you're not already there.

**6.1** Click **Refresh** (top right). **What you should see:** a default
"Dashboard refreshed." toast, and all the cards below reload.

**6.2** Click **Ask AXIOM** (top right, next to Refresh). **What you
should see:** you're taken straight to the AXIOM chat screen (§3.12) — a
shortcut, not a different chat.

**6.3** If a source has gone stale or a pipeline has a real incident
against it, a colored banner appears near the top with a button
**Investigate**. On the demo tenant (§1.4B), this banner should be
visible right now, since `demo_reset.mjs` deliberately creates one real
open incident. Click **Investigate**. **What you should see:** you're
taken to the **Incidents** screen (Section 7 covers it in full — come
back here after).

*(If you're on your own fresh-signup account from §1.4A instead, you
likely won't have an incident yet at this point in the guide, so this
banner won't appear — that's correct, not a bug. Come back to this step
after Section 7 if you want to see it.)*

**6.4** Find the **card listing pending approvals** (it'll show a count
badge if anything's pending, otherwise the empty state below). If you
happen to have a real pending approval sitting there (e.g. mid-Part-D of
Section 3), you can click **Approve** or **Reject** directly from this
card — same underlying action as everywhere else this guide covers it,
just a third entry point. **What you should see on success:** a plain
"Approved." or "Rejected." toast.

**6.5** Find the **recent pipeline runs** card. Click **View all** (top
right of that card). **What you should see:** you land on **Pipelines**
(§3.3).

**6.6** Find the **AXIOM activity** card (your recent chat sessions).
Click **Open** (top right) to jump to chat, or click any individual
session row to jump straight into that conversation.

**Empty states worth knowing** (you'll see these on a brand-new account
before you've done anything else): *"No pipeline runs yet."*, *"Nothing
pending approval."*, *"No conversations with AXIOM yet."* None of these
are errors — they're the honest zero-data state.

---

## 7. INCIDENTS — including one that's already real

*(~7 minutes. Best done on the demo tenant, §1.4B — it has a real incident
already waiting; on your own fresh account it'll mostly be empty states
until you log one yourself.)*

Incidents lives inside AXIOM's sidebar domain (see the note in §2.2 if
you haven't been there yet this session) — click **AI Employees** →
**AXIOM**'s card if you're starting fresh from Dashboard, then click
**Incidents** in the sidebar that appears. If you're continuing straight
from an earlier section that already put you in that domain (Sources,
Pipelines, Quality, etc.), it's already right there.

**7.1 — If you're on the demo tenant:** you should already see one row —
severity **HIGH**, titled **"HR Sync Pipeline failed — source file not
found."** This is real, not staged content dressed up as a demo: it was
created by `demo_reset.mjs` deliberately breaking the "Employee Records"
source's file path and letting a real pipeline run fail against it.
Click the row to see its full detail if the table exposes one, or just
note it — you'll act on it in 7.4.

**7.2** Click **+ Log Incident**.

**7.3** In the window titled **Log Incident**:
- **Title**: type `Test incident — manual entry`
- **Description**: type `Logged manually while testing the Incidents screen.`
- **Severity**: pick `medium`
- **Pipeline (optional)**: pick **Sales Ingestion Pipeline**

Click **Log Incident**.

**What you should see:** a `` "Test incident — manual entry" logged. ``
toast, and a new row in the table with status **open**.

**7.4** Now resolve one. On the demo tenant, click **Resolve** on the
real **"HR Sync Pipeline failed"** row (on your own account, resolve the
one you just logged instead — you don't have another). A window titled
**Resolve Incident** opens with a required **Resolution notes** field.
Type: `Confirmed and closed during self-test walkthrough.` and click
**Mark Resolved**.

**What you should see:** an "Incident resolved." toast, and that row's
**Resolve** button is replaced with a plain `—` (already-resolved rows
have no further action).

*(If you resolved the real demo incident and want the tenant back to its
original known-good state for next time — e.g. for someone else's
walkthrough — re-run `demo_reset.mjs`, §1.5. Nothing about resolving it
here breaks anything; it's just no longer "the incident that comes
pre-loaded.")*

**Empty state, if you're starting from zero:** heading *"No incidents,"*
body *"Nothing's on fire. Incidents raised by AXIOM or logged manually
will show up here."*

---

## 8. TRANSFORMS — the screen this guide never used to mention

*(~15 minutes — the largest single addition here. Transforms lives inside
AXIOM's sidebar domain, same as Data Sources/Pipelines/Quality/Incidents
— see the note in §2.2 if this is your first time there this session.
Click* **Transforms** *in that sidebar. Do this after §2.3 so a profiled
source exists to work against.)*

At the top: a **Data source** dropdown — select **Sales Orders**. Below
it, four tabs: **Natural Language**, **SQL Editor**, **Python Editor**,
**History**.

### 8.1–8.2 Natural Language tab

**8.1** In the box labeled *"Describe your transformation in plain
English,"* type:
```
Filter rows where quantity is greater than 2
```
Leave the language dropdown on **Auto**.

**8.2** Click **Generate**.

**Cost: 1 real AI call.**

**What you should see:** the button reads "Generating…" briefly, then real
generated code appears where the placeholder text *"-- Generated code
will appear here"* was. A badge reads either **Grounded in real schema**
(it read Sales Orders' actual columns) or **No schema available**. A
button appears: **Send to SQL Editor** (or **Send to Python Editor**,
depending what it generated) — click it.

**What you should see:** you're switched to that tab with the generated
code already loaded in the editor.

### 8.3 SQL Editor tab

**Correction, 2026-08-19 (finding 19): this section previously claimed
Dry Run/Execute against Sales Orders return real row data — they don't,
and that was a guide error, not a product bug.** `SqlRunner` (the module
behind both buttons) only supports `postgres`/`mysql` source types by
design — a CSV source like Sales Orders (the only kind this guide's
credentials-free walkthrough can give you, see §13) hits a clean,
honest, explicit rejection, not real execution. Confirmed live: typing
any query and clicking Execute against Sales Orders shows the plain
error text `SqlRunner does not support source type 'csv'.` — no crash,
no silent wrong result, no AI cost. That error message *is* the correct
thing to see here; treat seeing it as this step passing, not failing.

With code loaded from 8.2 (or type your own, e.g.
`SELECT * FROM sales_orders LIMIT 5`), with **Sales Orders** selected as
the data source:

1. Click **Dry Run**. **What you should see:** the same
   `SqlRunner does not support source type 'csv'.` message (dry-run hits
   the identical source-type check before it ever gets to planning
   anything).
2. Click **Execute**. **What you should see:** the same message again.

**If you have real Postgres/MySQL credentials of your own** (this guide
can't hand you any, see §13's "Non-CSV source types" note) and connect
one as a source instead, this is where you'd actually see the original
behavior this section used to describe: a real **Query Plan** on Dry Run,
and a real **Result Preview** with row data and a stats line (e.g.
`` 4 rows · 82ms ``) on Execute — not tested as part of this guide.

**If you haven't picked a data source at the top:** both buttons toast
`Select a data source first.` instead of showing the source-type error —
expected, not a bug.

### 8.4 Python Editor tab

1. With code loaded (or type something simple), click **Preview (100
   rows)**. **What you should see:** a result section labeled **Preview**
   with real output.
2. Click **✨ Explain**.

**Cost: 1 real AI call.**

**What you should see:** the button reads "Explaining…" briefly, then a
real plain-English explanation card appears below — a genuine AI read of
the code, not a canned description.
3. Click **Execute** to actually run it for real (same result shape as
   Preview, but not row-capped the same way).

### 8.5 History tab

Click the **History** tab. **What you should see:** every transform you
just ran (from both 8.3 and 8.4) listed with columns **Code**, **Type**,
**Origin** (`AXIOM` if AXIOM ran it via chat, `Manual` if you ran it here
— everything above is `Manual`), **Status**, **Rows**, **Created**.

Click **Replay** on any row. **What you should see:** a "Loaded into
editor — review and run." toast, and that code reloads into its original
tab, ready to re-run — zero AI cost, it's replaying, not regenerating.

**Empty state, if you haven't run anything yet:** heading *"No transforms
run yet,"* body *"Real SQL and Python transforms you run from this
screen — or AXIOM runs on your behalf in chat — appear here."*

---

## 9. SETTINGS — five tabs, one real credential flow

*(~10 minutes. Click* **Settings** *in the sidebar, bottom of the ADMIN
section. All five tabs are enabled for you here since a fresh signup's
first user is always Owner — a non-owner/admin would see the same tabs
with every field disabled and a "read-only" notice instead, which this
guide doesn't walk through since it needs a second real member to test.)*

Tabs across the top: **Workspace**, **Notifications**, **AI Model**,
**Theme**, **API Keys**.

**9.1 Workspace tab.** Fields: **Workspace name**, **Timezone** (try
`Asia/Kolkata`), **Description**. Change one, click **Save**. **What you
should see:** "Settings saved." toast.

**9.2 Notifications tab.** Fields: **Slack webhook URL**, **Alert email**,
and a checkbox group labeled **Notify on** with exactly four options:
**Incident created**, **Pipeline failed**, **Deployment failed**,
**Approval required**. Toggle a couple, click **Save**.

**9.3 AI Model tab.** A dropdown labeled **Model** with three options:
**Use plan default**, **Gemini 3.5 Flash**, **Llama 3.3 70B (Groq)**. Pick
**Llama 3.3 70B (Groq)** and **Save** — this is a real per-tenant
override; your next chat message or plan generation should show
`provider: groq` instead of `gemini`. Set it back to **Use plan default**
afterward if you don't want every remaining AI call in this guide pinned
to Groq.

**9.4 Theme tab.** Three buttons: **Light**, **Dark**, **System** — click
each, watch the page actually re-theme, and note the status line at the
bottom (*"Currently rendering: Dark"* etc.) confirms which one is active.
This setting follows your account across devices (different from the
quick theme-toggle icon in the topbar, covered in Section 12, which is
local-only and doesn't offer System).

**9.5 API Keys tab — the one real credential flow in the app.** Read the
notice first: *"API keys are for reference and audit today — nothing in
AXIOM currently accepts one as a request credential. Authenticating
requests with a key is planned but not yet built."* Type a name (e.g.
`CI pipeline`) and click **Create**.

**What you should see:** a modal titled **API key created**, warning text
*"Copy this now — for your security, it won't be shown again,"* the raw
key, a **Copy** button (toasts "Copied to clipboard." on click), and
**Done**. Close it, and the key now appears in the list — masked, with a
**Revoke** button. Click **Revoke** on it. **What you should see:** a
"Key revoked." toast and a **Revoked** badge in place of the button.
**Worth remembering while you test this:** per the notice above, this key
was never usable to authenticate anything in the first place — you're
testing the CRUD lifecycle, not a real credential.

---

## 10. APPROVALS — as its own screen, not just the inline card

*(~4 minutes. Click* **Approvals** *in the sidebar. If you did the
optional aside at §3.29, you may already have seen this screen with a
real pending item on it — this section documents it either way.)*

This screen is deliberately simple: a title, a table, no filters, no
search, no "+ New" button of any kind (everything on it arrives from
elsewhere — AXIOM's approval gate, or a CI/CD deployment gate — nothing is
manually created here). Each row has **Approve** and **Reject**.

One thing worth noticing if you have any real rows: a badge on each row
reads either **Agent Action** or **CI/CD Deployment** — this screen is a
merged view of two genuinely different backend sources (AXIOM task
approvals and CI/CD deployment gates) presented with identical Approve/
Reject buttons, even though they dispatch to different underlying
endpoints. Functionally fine, just worth knowing they're not the same
kind of thing under the hood.

**Empty state** (the likely state unless you timed §3.29's aside):
heading *"Nothing pending approval,"* body *"Agent actions and CI/CD
deployments that need a human sign-off will show up here."*

---

## 11. GOVERNANCE — Lineage, Contracts, Audit Log

*(~10 minutes. Governance lives inside AXIOM's sidebar domain, same as
Data Sources/Pipelines/Quality/Incidents/Transforms — see the note in
§2.2 if this is your first time there this session. Click*
**Governance** *in that sidebar. Three tabs:*
**Lineage**, **Contracts**, **Audit Log**. *One naming trap worth flagging
up front: this screen's* **Audit Log** *tab is real, live data — it is a
completely different thing from the sidebar's separate* **Audit Logs**
*item further down (that one's a stub page, see Section 13). Same words,
two different screens.)*

**11.1 Lineage tab** (default). Shows **Nodes (N)** and **Edges (N)**
cards — these are populated automatically as you add sources and
pipelines earlier in this guide, not something you create by hand here.
Empty state if you haven't done Section 2/3 yet: *"No lineage yet,"*
*"Lineage nodes are created automatically as you add sources and
pipelines."*

**11.2 Contracts tab.** Click **+ New Contract** (disabled until you have
at least one source — you should by now). In the window titled **New Data
Contract**:
- **Name**: `Sales Orders schema contract`
- **Producer source**: pick **Sales Orders**
- **Consumer description**: `Used by the pipeline and quality checks in this guide.`

Click **Create**. **What you should see:** `` "Sales Orders schema
contract" created. `` toast, and a new row.

**11.3** On that row, click **Validate**. **What you should see:** either
"Contract validated." or "Validation failed." — both are real outcomes
depending on whether the source's actual current schema matches what the
contract expects; either is a legitimate result to see, not a sign
something's broken.

**11.4 Audit Log tab.** Click it. **What you should see:** a real,
chronological log of governance/approval actions taken in this workspace
— creating this contract, validating it, any approvals you acted on
earlier in the guide. Empty state if genuinely nothing's happened yet:
*"No audit events yet," "Every governance and approval action taken in
this workspace is logged here."*

---

## 12. APP SHELL SWEEP — click each of these and note what happens

*(~5 minutes. This section is deliberately just a list of things to click,
not a description of what they do — several of these are dead or
placeholder, and the point is for you to notice which ones on your own
before checking Section 14. Do this from any screen.)*

1. Press **Ctrl+K** (or click the search bar at the top of the screen that
   says **"Search or run a command…"**). A command palette opens. Type a
   few letters of any nav item's name. Try pressing the **↓** arrow key,
   then **Enter**. Try clicking a result with your mouse instead. Try
   **Escape**.
2. Click the small collapse-icon at the bottom of the sidebar (no visible
   text, hover for a tooltip).
3. Click the **Production** label near the top of the sidebar (below the
   logo, with a chevron next to it — looks like a workspace switcher).
4. Click your account avatar (top right of the topbar). A dropdown opens
   showing your email and role. Click **Log out** — only do this last,
   since it ends your session (you'll need to log back in for anything
   further; §1.7 has the login screen's full field list if you need it).
5. Before logging out: click the sun/moon icon next to your avatar a
   couple of times.
6. If you know where to look for a notifications bell in the topbar: look
   again. (This isn't a trick — see Section 14 for what's actually going
   on there.)

Once you've clicked through all of these, check Section 14's known-issues
list against what you actually saw.

---

## 13. WHAT'S DELIBERATELY NOT IN THIS GUIDE

**Fast path, if you're short on time:** Sections 1–5 (the original core
walkthrough) plus Section 6 (Dashboard) cover the product's actual
spine — source → pipeline → quality → Tasks — in well under 90 minutes on
their own. Sections 7–12 are real coverage, not padding, but you can stop
after Section 5/6 and still have exercised everything load-bearing.

These are left out on purpose, not forgotten:

- **Billing** — the entire screen is read-only informational copy
  ("handled manually... contact us," "coming soon"). There is no button
  anywhere on it to click.
- **Non-CSV source types** (Postgres, MySQL, REST API, Google Sheets) —
  each needs real, reachable database/API credentials this guide can't
  hand you; the CSV path in Section 2 exercises the identical Data
  Sources screen and backend path.
- **Team: changing an existing member's role, and the last-owner
  removal guardrails** — genuinely need a second real, already-established
  member to test against meaningfully; §4.4's Viewer invite only covers
  the invite-and-accept half of this screen.
- **`investigate_incident` task shape** — see the note at the very top of
  this guide's change history: this one *is* fully implemented (same code
  path as the two shapes Section 3 already exercises), just never chosen
  for a worked example here. Try it yourself any time via **+ Start a
  Task**, type type `Investigate the open incident on my HR Sync
  Pipeline` (or your own logged incident from §7.2/7.3), and pick task
  type **"Investigate incident."** — costs 1 more AI call, not otherwise
  different from anything else in Section 3.

---

## 14. KNOWN ISSUES — do NOT report these as findings

Everything below is already known — confirmed by reading the actual
source, not guessed. If you notice one of these while testing, it's not a
new discovery; if you notice something that *isn't* on this list, that's
the kind of thing worth writing down.

- **`step_budget_used` only increments when a task step succeeds** — a
  step that fails and exhausts its retry budget consumes none of the
  step budget. Whether that's intended or a real gap is itself an open
  question, not something already decided either way.
- **`BusinessRules.create_rule()` cannot create any of its 8 advertised
  business-rule types** — it validates against the wrong internal type
  list, so every one of them is rejected as "Unknown rule_type." (This is
  separate from the plain quality rules Section 3 Part B and this guide's
  §7/§9 exercise, which work correctly — it's specifically the
  higher-level "business rules" capability, not reachable from any screen
  in this guide.)
- **CI/CD's schema-drift check has always silently no-op'd** — it imports
  a model module that doesn't exist anywhere in this repo, caught by a
  bare `except ImportError` that reports `"skipped"` instead of failing
  loudly. Every CI/CD risk score ever computed has excluded schema-drift
  detection entirely.
- **CI/CD's auto-rollback monitor has no live trigger** — the real
  pipeline executor never calls the endpoint that would feed it the data
  it needs to actually decide whether to roll back. The rollback logic
  itself is only ever exercised by tests calling the endpoint directly.
- **`contract_service.py`'s schema-validation reads snapshots in a flat
  shape that never actually occurs** — real schema snapshots are nested
  per table name; this bug means validating a contract against any
  genuinely profiled source (like the one you'll create in Section 11)
  will report every expected column as missing. This is real and current
  — if §11.3's Validate reports failures that don't make sense given a
  correctly profiled source, this is why, not a new bug.
- **API keys (Section 9.5) don't authenticate anything** — the notice in
  the UI already tells you this; it's the full CRUD lifecycle with no
  request-authentication path wired up yet, by design at this stage of
  the build.
- **`NotificationsPanel` has no trigger anywhere in the UI at all** —
  it's not just hardcoded placeholder data (four fixed fake notifications,
  no real backend feed, confirmed by reading the component directly); the
  component itself is never imported or rendered by the app's layout, so
  there is no bell icon, no button, no way to open it by clicking
  anything. If Section 12 had you looking for a notifications trigger and
  you didn't find one — that's correct, not something you missed.
- **The command palette's arrow-key and Enter-to-select don't exist**,
  despite the `↓`/`↵` hints shown in the UI implying they do — confirmed
  by reading the component: the only keyboard handling wired up is
  Escape-to-close. Mouse click is the only way to actually select a
  result today.
- **The sidebar's "Production" workspace switcher is not a real
  switcher** — clicking it only fires a toast reading "Workspace switcher
  — coming in Phase 15." There's nothing to switch to.
- **Automations, Analytics, and Audit Logs (the sidebar item, not
  Governance's Audit Log tab — see Section 11's note) are all stub
  pages** — each renders a plain "this screen is a routable stub for now"
  placeholder. Reachable from the sidebar, intentionally not built yet.
