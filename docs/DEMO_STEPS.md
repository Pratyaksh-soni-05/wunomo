# AXIOM Demo — Beginner Step-by-Step Guide

This assumes you have never recorded this demo before and don't have the
product's screens memorized. Every click, every window, every thing you
type is spelled out. If a step says "click X," X is the exact word or icon
you're looking for — nothing is assumed.

Print this, or open it on your phone propped next to your monitor.

---

## PART 1 — THE STORY (read this so you can explain it in your own words)

Here's what you're demoing, in plain language:

You run a small company. You use a product called **AXIOM** to watch over
your data — the spreadsheets and databases your business runs on, and the
automated jobs ("pipelines") that move that data around every day. Right
now you have two of those jobs running: one that pulls in sales orders,
and one that syncs your employee records from a spreadsheet.

The employee-records job just broke. Someone (or something) changed the
file path it was pointed at, so when it tried to run this morning, it
looked for the spreadsheet and couldn't find it. It failed, and it logged
exactly one problem report ("incident") about it — not ten duplicate
alerts, just one clear one.

That's what the setup script (`demo_reset.mjs`) actually builds for you,
every single time you run it: it creates the company, uploads two real
spreadsheets, sets up both jobs, runs them for real, and then deliberately
breaks the employee-records one in this exact way — a missing file — so
there's something real and true for AXIOM to find. Nothing is faked or
scripted; the failure is a real computer error, not a prop.

In the demo: **AXIOM investigates the failure and correctly explains what
broke.** Then you ask it to fix the pipeline, and because that's a change
to real data, **AXIOM won't just do it — it asks a human to approve the
action first.** That's the point: an AI that acts, but only with sign-off.
You approve it, fix the actual broken setting yourself (something only a
person should touch), and AXIOM's next run succeeds for real.

---

## PART 2 — PRE-FLIGHT CHECKLIST (do all of this before you press record)

Work through every box in order. Don't skip ahead.

### Step 1 — Check Docker is running
- [ ] Open a terminal (PowerShell). Click the Windows Start button, type
  `powershell`, press Enter.
- [ ] Type this and press Enter:
  ```
  cd "C:\Pratyaksh Personal\My Projects\ai workforce\dataops-agent"
  ```
  (Adjust the path if your project folder is somewhere else.)
- [ ] Type this and press Enter:
  ```
  docker compose ps
  ```
- [ ] **What you should see:** a table listing 5 rows —
  `dataops_backend`, `dataops_beat`, `dataops_celery`, `dataops_postgres`,
  `dataops_redis` — each with a `STATUS` column saying **`Up ...`**
  (something like "Up 6 hours"). If you see that, Docker is fine, skip to
  Step 2.
- [ ] **If the table is empty or the command errors:** everything is
  stopped. Start it with:
  ```
  docker compose up -d
  ```
  Wait about 15 seconds, then run `docker compose ps` again and confirm
  all 5 rows say `Up`.

### Step 2 — Reset the demo data
- [ ] In the same terminal, go up one folder:
  ```
  cd ..
  ```
- [ ] Run the reset script:
  ```
  node dataops-agent/scripts/demo_reset.mjs
  ```
- [ ] This takes about 15–30 seconds. **What you should see** at the end,
  exactly this shape (your numbers/IDs will be different each time —
  that's normal):
  ```
  == Demo state ready ==
  Tenant:        AXIOM YC Demo  (...)
  Login email:   demo@axiom-yc.ai
  Login password:AxiomDemo2026!
  Healthy pipeline: Sales Ingestion Pipeline  (...)
  Broken pipeline:  HR Sync Pipeline  (...)
  Broken source:    Employee Records  (...)
  Open incident:    (...)

  Frontend: http://localhost:3000/login
  ```
- [ ] **If it prints `DEMO RESET FAILED`** instead: something's wrong
  with Docker (go back to Step 1) — don't try to record until this
  script finishes cleanly.

### Step 3 — Copy the pipeline ID (you'll need this later, in Step 6 of Part 2 and Beat 3 of the recording)
There is no way to see this ID anywhere in the actual product screens —
it only exists in this terminal output. So you grab it now, before
recording.
- [ ] In the output from Step 2, find the line that says
  `Broken pipeline:  HR Sync Pipeline  (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)`
- [ ] Select and copy just the ID part — the long string of letters,
  numbers, and dashes inside the parentheses (not the parentheses
  themselves).
- [ ] Open Notepad (Start menu → type `notepad` → Enter) and paste it
  there. Keep this Notepad window open on a second monitor, or minimized
  in your taskbar, so you can copy it again quickly during Beat 3 of the
  recording.

### Step 4 — Check the frontend is running, as a real production build (not the dev version)
- [ ] In your terminal:
  ```
  netstat -ano | findstr :3000
  ```
- [ ] **If you see any lines of output:** something is already listening
  on port 3000. Find the number at the very end of that line (the
  Process ID), then run:
  ```
  taskkill /PID <the number you saw> /F
  ```
- [ ] Now start the real build fresh:
  ```
  cd dataops-agent/frontend
  rmdir /s /q .next
  npm run build
  ```
- [ ] Wait for it to finish (about a minute). **What you should see:** a
  list of routes/page names and sizes, ending without any red "Failed to
  compile" text.
- [ ] Start the server:
  ```
  npm start
  ```
- [ ] **What you should see:** `Ready in ...ms` printed in the terminal,
  and it stays open (this window must stay running the whole time you
  record — don't close it).
- [ ] **Why this matters:** the dev version (`npm run dev`) shows a small
  build-status badge in the corner of the browser that makes the product
  look unfinished on camera. `npm start` genuinely doesn't have it —
  confirmed by screenshot comparison.

### Step 5 — Check your AI assistant (AXIOM) is responding
- [ ] Open a **second** terminal window (leave the one running the
  frontend alone). `cd` to the `ai workforce` folder like in Step 2.
- [ ] Run:
  ```
  node dataops-agent/scripts/demo_chat_test.mjs "hi"
  ```
- [ ] **Good result:** a block starting with `status: 200` and
  `elapsed:` under about 10 seconds, followed by a real reply from
  AXIOM.
- [ ] **Bad result:** `status: 500`, or it hangs for 30+ seconds before
  failing. This means the AI service is temporarily overloaded — it's
  not your fault and nothing on your end is broken. Wait 15 minutes and
  try the same command again. Do not start rehearsing until this comes
  back clean — a failed AI response mid-recording is the single most
  likely thing to ruin a take.

### Step 6 — (Only if Step 5 failed) Switch which AI provider you're using
AXIOM can run on either of two AI services — Google's ("Gemini") or
Groq's. Switching doesn't change anything you see on screen, so use
whichever one is working.
- [ ] Open both of these files in Notepad (or any text editor):
  `dataops-agent\.env` and `dataops-agent\backend\.env`
- [ ] In **both** files, find the line that starts with
  `PRIMARY_LLM_MODEL=` and change the part after the `=` to one of:
  - `gemini-3.5-flash` (Google)
  - `llama-3.3-70b-versatile` (Groq)
- [ ] Save both files.
- [ ] Back in your terminal (in the `dataops-agent` folder):
  ```
  docker compose up -d --force-recreate backend celery_worker
  ```
  (Do **not** use `docker compose restart` — it does not pick up the
  file changes you just made.)
- [ ] Wait about 10 seconds, then repeat Step 5's test command. Confirm
  it now comes back clean before moving on.

### Step 7 — Browser setup
- [ ] Open a normal Chrome/Edge window (not required to be Incognito,
  since you'll be logging in on purpose).
- [ ] Close every other tab. You want exactly one tab, one window.
- [ ] Go to: `http://localhost:3000/login`
- [ ] Log in with:
  - Email: `demo@axiom-yc.ai`
  - Password: `AxiomDemo2026!`
- [ ] **What you should see:** you land on the **Dashboard** screen —
  a page with the word "Dashboard" as a heading, an orange warning banner
  near the top, and several small number cards below it.
- [ ] Press **F11** to make the browser full-screen (hides the address
  bar, tabs, and bookmarks bar — a much cleaner look on camera). Press
  F11 again any time you need to exit full-screen.
- [ ] Turn off notifications: Windows Start → type "focus assist" →
  turn it **On** (or set to "Alarms only") so no Windows notification
  popups can appear mid-recording.

### Step 8 — Screen recorder settings
- [ ] If you don't already have a recorder, Windows has one built in:
  press **Win + G** to open Xbox Game Bar, then click the round record
  button (or press **Win + Alt + R** to start/stop directly, no menu).
- [ ] Recommended settings: 1920×1080 resolution, record the browser
  window (not the full desktop — one less thing visible by accident),
  microphone on and tested with one spoken sentence played back before
  the real take.
- [ ] Do one 5-second test recording right now and play it back — confirm
  you can both see the screen clearly and hear your own voice.

**All boxes checked? You're ready to record.**

---

## PART 3 — THE RECORDING, STEP BY STEP

Target length: **under 3 minutes** of footage (excluding the one planned
cut in Beat 5). Running total shown after each beat.

Legend: 🎬 = press record starts/resumes here · ✂️ = stop recording here

---

### 🎬 Beat 0 — Opening (talking beat, no clicks)
**Running total: 0:00 → 0:15**

1. **WHAT I DO:** Look at the camera (or start your voiceover). Nothing
   on screen yet, or show the Dashboard already loaded but don't
   interact with it yet.
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY** (read this aloud):
   > "Data pipelines fail quietly. By the time someone notices, it's
   > already cost hours of bad decisions on bad data. We built AXIOM —
   > an AI DataOps engineer that watches your pipelines, diagnoses
   > failures like a senior engineer would, and only acts with your
   > sign-off. Here's a real pipeline, failing right now."
4. **WHAT I SHOULD SEE:** N/A (talking beat).
5. **IF IT GOES WRONG:** Flub a line? Just stop, take a breath, and
   re-say the sentence — you'll cut the stumble out in editing. No need
   to restart the whole recording for this beat alone.

---

### Beat 1 — Show the problem on the Dashboard
**Running total: 0:15 → 0:25**

1. **WHAT I DO:** You should already be on the Dashboard from Part 2,
   Step 7. If not: click **Dashboard** — the first item in the left
   sidebar, near the top, with a small grid icon next to it.
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY:**
   > "Here's AXIOM's live view of this company's data stack. Real KPIs,
   > real incident."
   (As you say this, move your mouse to point at, in order: the orange
   banner near the top, then the "Open Incidents" number card.)
4. **WHAT I SHOULD SEE:**
   - An orange/warning banner near the top of the page that starts with
     **"HR Sync Pipeline failed — source file not found."**
   - A row of small cards below it, including one labeled
     **"Open Incidents"** showing the number **1**, and one labeled
     **"System Health"** showing **75%**.
5. **IF IT GOES WRONG:** If the banner isn't there, or "Open Incidents"
   shows 0 — you forgot to run the reset script (Part 2, Step 2), or ran
   it and then accidentally clicked "Resolve" somewhere already. Stop,
   re-run `node dataops-agent/scripts/demo_reset.mjs`, refresh this page,
   and start the recording over from Beat 0.

---

### Beat 2 — Ask AXIOM to investigate
**Running total: 0:25 → ~1:10 (this beat has a real wait in it)**

1. **WHAT I DO:** In the left sidebar, under the **WORKSPACE** heading,
   click **AXIOM** (it has a small blue **"Live"** badge next to it —
   that's how you know it's the right one, not "AI Employees" above
   it). Then click inside the text box at the very bottom of the
   screen — it has faint grey placeholder text reading "Ask AXIOM
   anything about your data...".
2. **WHAT I TYPE** (into that text box, then press Enter or click the
   **Send** button just to the right of the box) — type this exact
   sentence, don't shorten it:
   ```
   Check the open incidents. For any incident you find, use its real incident ID to triage the root cause and summarize what happened.
   ```
   **Do not** click the small grey **"List open incidents"** button that
   sits under the text box (it's one of five shortcut buttons — you'll
   also see "List my data sources," "Show failed pipeline runs," etc.).
   That button only fills the box with the words "List open incidents"
   — a much shorter request that's never been tested for this demo and
   would only do half the job (it finds the incident but doesn't
   necessarily dig into *why* it happened). Those quick buttons are a
   real product feature, just not the one to use here — type the full
   sentence above instead.
3. **WHAT I SAY** (say this while it's thinking — it takes a real 10–50
   seconds, this isn't scripted or sped up):
   > "It's pulling up the incident, then running root-cause analysis
   > against the actual failed run — this is a real AI call, not a
   > canned response, so it does take a few seconds."
4. **WHAT I SHOULD SEE** (in this order, top to bottom):
   1. Your own message appears first, right-aligned, in a solid dark
      bubble.
   2. Below it, on the left, a small pulsing dot with the words
      **"AXIOM is thinking…"** — this is normal, just wait. After 5
      seconds it changes to "AXIOM is still thinking… (Ns)" and keeps
      counting up. This is expected and can run anywhere from 10 to 50+
      seconds — don't refresh the page or click anything while it's
      counting.
   3. When it finishes, the thinking indicator is replaced by AXIOM's
      written reply, in a lighter card/box on the left. Read for it to
      name the exact broken file path (something like
      `employee_data_MISSING.csv`) and explain that's the root cause.
   4. **Below that reply text** (always below, never above it), one or
      two small rows appear, each showing a tool name — you should see
      `list_open_incidents` and `triage_incident` — with a green
      **"Completed"** badge on the right side of each row. These are
      collapsed by default (you'd have to click one to expand it); you
      don't need to click into them on camera, just knowing they're
      there and green is enough to confirm it worked.
5. **IF IT GOES WRONG:**
   - **You see two `triage_incident` rows, both green "Completed"**
     (not one): this is fine and expected sometimes — AXIOM tried a
     guessed ID first, got a clean "not found" answer, and correctly
     retried with the right one. It does NOT show as an error or red
     anything on screen; it's genuinely invisible unless you click to
     expand those rows. Keep rolling, don't react to it.
   - **It's been over 90 seconds with no reply, or you see a red error
     message in the chat:** the AI service hit a real, temporary limit.
     **Stop recording.** Wait 15 minutes, re-run the Step 5 "hi" test
     from Part 2 to confirm it's healthy again, then **reset the demo
     data again** (Part 2, Step 2 — because this failed attempt didn't
     save a clean incident state) and restart the whole recording from
     Beat 0.
   - **The reply doesn't mention the file path at all / seems generic:**
     don't panic on camera — you can still move to Beat 3. But note it,
     and consider re-recording this beat once quota allows for a
     cleaner take.

---

### Beat 3 — Ask AXIOM to fix it, and watch it stop for approval
**Running total: ~1:10 → 1:35**

⚠️ **The first time you ever do this beat, do it once before you start
rehearsing anything else** — this exact wording hasn't been confirmed
live yet. If it doesn't work as described below, use the backup wording
in step 2b.

1. **WHAT I DO:** Same text box, same conversation (don't start a new
   chat). Click into the box. Before typing, switch to your Notepad
   window, copy the pipeline ID you saved in Part 2, Step 3, then switch
   back to the browser.
2. **WHAT I TYPE** (paste your ID in place of `<PASTE_PIPELINE_ID>`,
   keeping everything else exactly as written):
   ```
   Please run a backfill on pipeline <PASTE_PIPELINE_ID> (HR Sync Pipeline) for today, so it's ready to reprocess once the source is fixed.
   ```
2b. **BACKUP WORDING** (only use this if the first version doesn't
   trigger an approval request — see "IF IT GOES WRONG" below):
   ```
   Trigger a backfill run on pipeline <PASTE_PIPELINE_ID> for the date range 2026-07-24 to 2026-07-24, to reprocess it once the source is fixed.
   ```
   (Replace `2026-07-24` with today's actual date in both places.)
3. **WHAT I SAY:**
   > "Watch this — because this would change real data, AXIOM doesn't
   > just act. It stops and asks for a human sign-off first. This is
   > the guardrail, not a suggestion."
   Stop talking there. Don't add anything implying approving will make
   it run automatically — that's not how it works yet, and the next
   beats explain why without saying so out loud.
4. **WHAT I SHOULD SEE:** A message appears saying something like
   **"Approval Required for 1 action(s): `backfill_pipeline` ... Approve
   or reject in the approval center."**
5. **IF IT GOES WRONG:**
   - **No approval message appears, and it looks like something just
     happened instead:** AXIOM likely called a different, ungated tool.
     Stop, re-run the demo reset (Part 2, Step 2 — get a fresh pipeline
     ID first, Part 2 Step 3), and try again using the backup wording
     from step 2b instead of the original. If the backup also doesn't
     trigger it, stop and don't record this beat live — come back and
     ask for a different approach rather than guessing on camera.
   - **A red error / 500 appears:** same recovery as Beat 2's "wrong"
     case — stop, wait, reset, restart from Beat 0.

---

### Beat 4 — Approve it
**Running total: 1:35 → 1:45**

1. **WHAT I DO:** Click **Approvals** in the left sidebar (it has a
   checkmark-in-a-box icon, near the bottom of the main list, just above
   the "ANALYTICS" section heading). Find the row that says
   `backfill_pipeline` under a column labeled REQUEST. In the ACTIONS
   column on the right, click the green **Approve** button.
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY:**
   > "I review it, and approve it. That's now a permanent, timestamped
   > record of who signed off and when — real governance, not a rubber
   > stamp."
   Pause. Then, still looking at the same screen:
   > "Now — the actual fix here needs a config correction only a
   > person should make. Let's go apply it."
4. **WHAT I SHOULD SEE:** The row disappears from the list once you
   click Approve (the table goes back to showing "Nothing pending
   approval" if that was the only item).
5. **IF IT GOES WRONG:** If clicking Approve shows an error: refresh the
   page once and check whether it actually went through anyway (look at
   whether the row is gone). If the row is still there and still says
   pending, click Approve again. This is a simple, reliable button —
   real problems here are unlikely.

---

### ✂️ Beat 5 — CUT. Apply the fix off camera.
**Not counted in your 3-minute total.**

1. **WHAT I DO:** Stop the recording (press your recorder's stop
   hotkey, e.g. **Win + Alt + R**). Switch to your terminal (the second
   one, not the one running the frontend). Run:
   ```
   node dataops-agent/scripts/demo_unbreak.mjs
   ```
2. **WHAT I TYPE:** Nothing else — just that one command.
3. **WHAT I SAY:** Nothing — you're not recording right now.
4. **WHAT I SHOULD SEE:** Two lines of output, the second one starting
   with `Now go trigger the HR Sync Pipeline`.
5. **IF IT GOES WRONG:** If it errors, check that Docker is still
   running (`docker compose ps` in the other terminal) and that you
   didn't run `demo_reset.mjs` again since Beat 0 started (running reset
   again mid-take would generate a *new* pipeline ID, making the one in
   your Notepad stale). If in doubt, it's safest to reset everything and
   restart the whole recording from Beat 0.

**When ready, start recording again** (same recorder hotkey) and
continue directly into Beat 6.

---

### 🎬 Beat 6 — Re-run it for real
**Running total: 1:45 → 1:53**

1. **WHAT I DO:** Click **Pipelines** in the left sidebar (a small
   wave/pulse icon, a few items below Data Catalog). Find the row named
   **HR Sync Pipeline**. In the ACTIONS column on the right, click
   **Trigger**.
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY:**
   > "With the source config corrected, let's re-run it."
4. **WHAT I SHOULD SEE:** Within a second or two, the STATUS badge next
   to HR Sync Pipeline's row under "Last:" flips from a red **failed**
   badge to a green **success** badge, and the timestamp next to it
   updates to just now.
5. **IF IT GOES WRONG:** If it still shows **failed** after clicking
   Trigger: the off-camera fix in Beat 5 didn't apply (maybe it was run
   against a stale/old pipeline ID). Stop, re-run
   `node dataops-agent/scripts/demo_unbreak.mjs` again, wait 3 seconds,
   click **Trigger** again. If it's still failing after that, do a full
   reset (Part 2, Step 2) and restart the whole recording from Beat 0.

---

### Beat 7 — Resolve the incident
**Running total: 1:53 → 2:08**

1. **WHAT I DO:** Click **Incidents** in the left sidebar (a small
   triangle/warning icon). Find the incident row. In the ACTIONS column,
   click the green **Resolve** button. A small popup window titled
   "Resolve Incident" appears with one text box labeled "Resolution
   notes." Click into that box.
2. **WHAT I TYPE** (into the "Resolution notes" box):
   ```
   Source file path was pointed at a missing file. Corrected the connection config and re-ran the pipeline successfully.
   ```
   Then click the green **Mark Resolved** button (it's greyed out until
   you've typed something in the box).
3. **WHAT I SAY:**
   > "And once the fix is confirmed, we close the loop."
4. **WHAT I SHOULD SEE:** The popup closes, and the incident's STATUS
   column changes from a red/orange "open" badge to a different badge
   indicating it's resolved.
5. **IF IT GOES WRONG:** The **Mark Resolved** button stays greyed out
   if the notes box is empty — make sure you actually typed in it first.
   No other realistic failure mode here; it's a simple form.

---

### Beat 8 — Show the dashboard after
**Running total: 2:08 → 2:18**

1. **WHAT I DO:** Click **Dashboard** in the left sidebar (back to the
   top item).
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY:**
   > "Same dashboard, thirty seconds later — for real."
4. **WHAT I SHOULD SEE:** The orange warning banner from Beat 1 is gone.
   "Open Incidents" now shows **0**. "System Health" should read higher
   than the 75% you saw in Beat 1 (it recalculates based on the last 7
   days of runs, so the exact number depends on timing — it will be
   visibly better, possibly 100%).
5. **IF IT GOES WRONG:** If the banner is still there or Open Incidents
   still shows 1: Beat 7's resolve didn't go through. Go back to
   Incidents, confirm the status, and redo Beat 7 if needed before
   continuing — don't narrate "it's fixed" over a screen that still
   shows it broken.

---

### Beat 9 — Governance: lineage and the audit trail
**Running total: 2:18 → 2:33**

1. **WHAT I DO:** Click **Governance** in the left sidebar (a small
   flag/marker icon). You'll land on a **Lineage** tab by default — two
   side-by-side tables titled "Nodes" and "Edges." Then click the
   **Audit Log** tab, third of the three tab labels near the top of the
   page (the other two are "Lineage" and "Contracts").
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY** (on Lineage):
   > "This is real data lineage — automatically tracked, not drawn by
   > hand — showing exactly how these two spreadsheets flow into their
   > pipelines."
   (then, after clicking Audit Log:)
   > "And here's that approval decision from a minute ago — who signed
   > off, and when. That's a real, permanent record."
4. **WHAT I SHOULD SEE:** On Lineage: a table with 6 rows under "Nodes"
   (including "Sales Orders" and "Employee Records") and 4 rows under
   "Edges." On Audit Log: at least one row referencing the approval you
   made in Beat 4.
5. **IF IT GOES WRONG:** If the Audit Log tab looks empty: this can
   happen if the reset script ran again after Beat 4 (which wipes audit
   history). Don't claim it shows something it doesn't — if it's empty,
   skip the second sentence of narration and just show Lineage.
   **Don't say** "every action AXIOM took is logged here" — only the
   approval decision itself is guaranteed to appear here, not every
   step AXIOM took this session.

---

### 🎬 Beat 10 — Closing (talking beat)
**Running total: 2:33 → 2:53**

1. **WHAT I DO:** Look at the camera again, or stay on the Dashboard/
   Governance screen as a calm backdrop.
2. **WHAT I TYPE:** Nothing.
3. **WHAT I SAY:**
   > "Everything you just saw is real — real pipeline, real failure,
   > real AI reasoning, no scripted responses. We're two engineers who
   > think every data team should have an AI DataOps engineer on staff,
   > not just dashboards that tell you something's wrong after the
   > fact. We're looking for our first design partners to build this
   > with — reach out if that's you."
4. **WHAT I SHOULD SEE:** N/A.
5. **IF IT GOES WRONG:** Same as Beat 0 — re-say a flubbed line, fix it
   in editing.

**Total running time: about 2:53** — leaves roughly 7 seconds of margin
under the 3-minute mark for natural pacing (people talk slightly slower
on camera than in a read-through).

---

## PART 4 — ONE-PAGE CHEAT SHEET

Keep this on a second screen or phone while recording. No explanations —
just what to click and what to type.

| # | Click | Type |
|---|---|---|
| 0 | *(talking, no click)* | — |
| 1 | Sidebar → **Dashboard** | — |
| 2 | Sidebar → **AXIOM** → click text box | `Check the open incidents. For any incident you find, use its real incident ID to triage the root cause and summarize what happened.` |
| 3 | Same text box | `Please run a backfill on pipeline <PASTE_ID> (HR Sync Pipeline) for today, so it's ready to reprocess once the source is fixed.` |
| 4 | Sidebar → **Approvals** → green **Approve** | — |
| ✂️5 | *(stop recording)* terminal → `node dataops-agent/scripts/demo_unbreak.mjs` | — |
| 🎬6 | Sidebar → **Pipelines** → **Trigger** on HR Sync Pipeline | — |
| 7 | Sidebar → **Incidents** → green **Resolve** → click notes box → **Mark Resolved** | `Source file path was pointed at a missing file. Corrected the connection config and re-ran the pipeline successfully.` |
| 8 | Sidebar → **Dashboard** | — |
| 9 | Sidebar → **Governance** → (Lineage shown) → click **Audit Log** tab | — |
| 10 | *(talking, no click)* | — |

**Pipeline ID for today's take:** ______________________________
*(fill this in from your terminal right before you hit record)*

---

## PART 5 — AFTER EACH TAKE

Whether the take worked or not, do this before trying again:

1. **WHAT I DO:** Switch to your terminal. Run:
   ```
   node dataops-agent/scripts/demo_reset.mjs
   ```
2. **WHAT I SHOULD SEE:** The same `== Demo state ready ==` block as
   Part 2, Step 2 — new IDs, but the same shape of output.
3. **Confirm it worked before recording again:**
   - Refresh your browser tab (it should still be logged in — if not,
     log in again with the same email/password).
   - You should land back on the Dashboard and see the orange warning
     banner and "Open Incidents: 1" again, exactly like Beat 1.
   - If you don't see that, something didn't reset cleanly — run the
     reset command a second time before trying to record again.
4. **Copy the new pipeline ID** into your Notepad window (Part 2, Step
   3) — it's different every time you reset, so last take's ID will not
   work for this take's Beat 3.
5. **If you switched AI providers mid-session** (Part 2, Step 6), you
   don't need to switch back between takes — leave it on whichever one
   is working.
