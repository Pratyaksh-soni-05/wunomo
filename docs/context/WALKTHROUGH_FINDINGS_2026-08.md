# Walkthrough Findings — 2026-08 (index)

Source: `docs/context/WALKTHROUGH_FINDINGS_2026-08.docx` — the user's raw
notes from the first end-to-end self-test of the product, written against
the expanded `docs/SELF_TEST_GUIDE.md`, with 22 screenshots embedded.

**This file is an index, not a replacement for the docx.** The docx stays
the image record — screenshots are referenced here by filename
(`imageN.ext`, matching `word/media/` inside the docx) so a later session
can find the right picture, not reproduced here. Item text below is
transcribed verbatim from the docx: original wording, typos, and phrasing
preserved exactly, not fixed, not interpreted, not merged, not resolved
into proposed solutions. Numbering matches the docx exactly (1–28) —
later sessions should cite findings by this number.

**Items 29+ are not from the docx.** They're findings surfaced by later
sessions working in this codebase (each row says which one), appended to
keep one single numbered list rather than a second competing index. Same
rules apply: logged, not fixed, not interpreted beyond what's stated.

**Class** is a light categorization only (Bug / Feature / Untested /
Design / Unclear) — it does not imply anything about severity, root
cause, or fix approach. **Guide section** is filled in only where the
user explicitly cited a step/section number in their own text — nothing
was inferred or looked up on their behalf. **Status** starts at `Open`
for every item.

---

| # | Finding (verbatim) | Guide section | Class | Screenshot(s) | Status |
|---|---|---|---|---|---|
| 1 | After first sign up of user or after every login it asks to choose workspace remove that whole thing i dont wanna choose a workspace we enter into the workspace of the last login and then in the dashboard we can toggle the workspaces but remove that pop up at the start of every login to choose workspace we directly login into the dashboard of last logged in workspace. | — | Feature | image16.jpg | Open |
| 2 | in the backend; Date and time after profiling the data source is not correct. Add data source page closes sometimes own its own on tab switichin g | — | Bug | image5.jpg (first part only — no screenshot found for the "Add data source page closes on tab switching" part) | Open |
| 3 | pipeline feature also date and time is wrong does not match the date and time of the machine or the pc. | — | Bug | image12.jpg | Open |
| 4 | In the axiom chat page there is no delete chat option for individual chat windows in the side panel | — | Feature | image15.jpg, image6.jpg | Open |
| 5 | remove the ask axiom button from the bottom left completely | — | Bug | image7.png | Open |
| 6 | Axiom -> view progress -> each task should have bigger box in which we can edit anf review at once in the edit plan tab. | — | Design | image10.png (uncertain — see note below) | Open |
| 7 | notification duration of every action or completion of the noptifications appearing on bottom left should be increased more smooth animation | — | Design | image4.png | Open |
| 8 | in step #3.30 in self test guide. After running the completion button is not coming back | §3.30 | Bug | image17.jpg (shared with item 9) | Closed (2026-08-17) |
| 9 | 3.30 → 3.32 steps in self test guide are not working | §3.30–3.32 | Bug | image17.jpg (shared with item 8) | Closed (2026-08-17) |
| 10 | increase all button sizes make them more aesthetic easy to click and only text is written when cursor hovers on top then a greay button boundary appears just like claude or any other website | — | Design | image21.jpg, image18.jpg, image3.jpg | Open |
| 11 | 'help' → should give error and not generate any plan in step 4.1 in self test guide but it is working and still appearing in the task list with plan approval | §4.1 | Bug | none identified | Open |
| 12 | when rejected the assurance box is not appearing back again | — | Unclear | image22.jpg (uncertain — see note below) | Open |
| 13 | Add re run buttons | — | Unclear | none identified | Open |
| 14 | step 4.50 in self test guide Terminal response not correct | §4.50 (as written) | Unclear | image20.png | Open |
| 15 | 4.54 check terminal output again | §4.54 (as written) | Unclear | image9.png | Open |
| 16 | in step 6.1 in self test guide cards not reloading after refresh | §6.1 | Bug | none identified | Closed (2026-08-17) |
| 17 | 6.3 → 6.4 check from different accounts | §6.3–6.4 | Untested | image11.png | Open |
| 18 | 6.6 → dosent go to the conversation when clicked | §6.6 | Bug | image1.png | Open |
| 19 | 8.3 → SQL execute and dry run not running for csv but it should as per the sel;f test guide from claude | §8.3 | Bug | image13.png | Open |
| 20 | got logged out randomly maybe after 1 hour | — | Bug | none identified | Open |
| 21 | incidents banner does not go from dashboard notifications evenm after resolving and checking the incident. No clode button to clode the popup on investigate prompt tab | — | Bug | image2.png | Open |
| 22 | Settings page full customize it. The timezone should be a drop down menu instead of manually typing timezone and after setting timezone it should work and should be correct according to machines timezone | — | Unclear | image14.png | Open |
| 23 | Onm first sign up some questionnaire is asked for more better understanding of user so store those answers in the user profile section in the setting tab | — | Feature | none identified | Open |
| 24 | Main change very important; PUT AXIOM in a sub folder in the dashboard with all the other employees. The side panel make it free free up some space. Like first i click on ai employees then i choose axiom and then the side panel changes accordingly and all axiom chat features appear in the side panel. Axiom is not the main employee is just the first on to be built so put it with all the other employees yet to come in a sub section. | — | Feature | none identified | Open |
| 25 | double verification for changing the mail or slack url anbd invalid email task should be there when the email not verified. | — | Feature | image8.png | Open |
| 26 | approvals: check from different accounts for cicd action/ agent action | — | Untested | image19.png | Open |
| 27 | The self test guide has nothing on testing the CICD and automations feature please see into that too. | — | Feature | none identified | Open |
| 28 | ALL OF THIS HAS TO BE AUTOMATED the user upload data in the axiom chat is what we want and then the ai employee carries out all the remaining steps on its opwnm is what the main idea is just like claude code try to make the possible . make it chat friendly all the major working the user does while chatting with axiom if data needed axiom asks for it user uploads the data csv and axiom puts it in datasources and does profiling and all other steps on its own this is what we want fully automated process to reduce human effort. | — | Feature | none identified | Open |
| 29 | Nav items are not role-filtered — every logged-in user sees the identical sidebar regardless of role (a Viewer sees Team, Billing, Settings, and CI/CD listed exactly like an Owner does) and only hits a wall once they actually try to use something inside those screens. Found while investigating the sidebar's real role-gating for the 2026-08 IA restructure proposal — confirmed directly by reading `navItems.tsx`/`Sidebar.tsx`/`layout.tsx`, none of which do any role-based filtering; all real enforcement is one layer down, at the page/control level. Not fixed — logged only, per instruction. | — | Bug | none | Open |
| 30 | Governance's own **Audit Log** tab (a real, live tab inside the Governance screen) has the identical name as the sidebar's separate **Audit Logs** item (a stub page, unrelated screen) — a genuine naming collision between two different things. Already documented once, in passing, in `docs/SELF_TEST_GUIDE.md` §11's own note about this exact collision. Logged here as its own findings-index item per instruction — explicitly not renamed this session. | §11 | Design | none | Open |
| 31 | `run_quality_checks` accepts any `pipeline_id` string, including one that matches no real pipeline, and returns a false "100% passed, no active quality rules" result instead of erroring. Root cause: `QualityRuleEngine.run_checks()` (`modules/quality/rule_engine.py:92-103`) queries `QualityRule WHERE pipeline_id == pipeline_id` with no existence check first — zero rows matched looks identical whether the pipeline is real-but-ruleless or the ID is complete garbage. Found live, 2026-08-17, verifying the findings-8/9 argument-resolution fix: the `sync_profile_quality` task shape's own allowed-tools list (`TASK_SHAPE_ALLOWED_TOOLS`, `task_planner.py`) has no pipeline-discovery tool, so its final step's `pipeline_id` can never be resolved to a real value by either resolution tier — the task still reached `COMPLETED`, but the last step's "success" was hollow (zero rules actually evaluated). Not fixed — logged only, per instruction. Two independent gaps, either fixable alone: give this task shape a pipeline-discovery step, and/or make `run_quality_checks` verify the pipeline exists before reporting a score. | — | Bug | T1_09_step3.png, T1_11_final_status.png (session scratchpad, not repo-committed) | Open |
| 32 | Tier 2's LLM-based argument adaptation (`_adapt_step_args`, `task_executor.py`, added 2026-08-16) can silently substitute a real but *wrong* entity's ID when the entity the plan actually meant doesn't exist at all, and the step then reports success. Found live, 2026-08-17: a `diagnose_pipeline_failure` task deliberately targeting a nonexistent "Zephyr Cargo Manifest Pipeline" saw its `pipeline_id` placeholder replaced with the real ID of the unrelated "Sales Ingestion Pipeline" (visible in `prior_results` from the same task's own `list_pipelines` call) — the tool call succeeded against that wrong pipeline, and the task reached `COMPLETED` reporting on the wrong entity's run history, no error anywhere. Contrast with the same session's item 31/§Tier-1 behavior: Tier 1 (`_resolve_step_args`) is deliberately built to never guess between candidates and leave a genuine non-match untouched; Tier 2 has no equivalent guardrail — its prompt asks the LLM to *fix* the arguments, and a plausible-looking real ID from `prior_results` satisfies that instruction even when nothing in the task's own evidence actually supports it being the right one. Not fixed — logged only, per instruction. A real fix likely means telling the adapt prompt it's allowed to say "no real match exists" instead of always returning a corrected value, and treating that as a genuine failure rather than a success. | — | Bug | T4_04_status_check.png (session scratchpad, not repo-committed) | Open |

---

## Closure notes (2026-08-17)

Items 8, 9, and 16 are closed together — all three trace to the same root
cause diagnosed 2026-08-16 (see `SESSION_LOG.md`'s 2026-08-16 and
2026-08-17 entries): Tasks generated a plan with plan-time argument
placeholders (e.g. `"source_id": "sales_orders_source_id"`) that no step
ever replaced with a real value, so every non-trivial task step referencing
an entity discovered by an earlier step failed every time — item 8's
"completion button not coming back" and item 9's "3.30 → 3.32 not working"
are that failure as experienced in the self-test guide's own walkthrough;
item 16's "cards not reloading after refresh" was the same non-terminal,
stuck-task state observed from the Tasks list view instead of the task
detail view.

**Closed on the strength of three real, human-run tasks reaching
`COMPLETED` today, live, on Gemini** (not mocked, not "failed legibly" —
see Workflow Rule 10): `sync_profile_quality` on the real Sales Orders
source, `diagnose_pipeline_failure` against the real HR Sync Pipeline
(found by name via the new `list_pipelines` tool, no ID supplied),
and `investigate_incident` against the real HR Sync incident, including a
real `resolve_incident` mutation. Every approval gate hit during those
three runs displayed the real, resolved argument values before execution,
and what executed matched what was displayed, confirmed via screenshot
at each gate.

**This does not mean argument resolution is now bug-free** — see items 31
and 32 above, both found live during this same verification pass. Neither
contradicts that 8/9/16's specific symptom (tasks structurally unable to
reach `COMPLETED`) is fixed; both are different, narrower gaps the fix's
own live testing surfaced.

## Notes on screenshot correlation

The docx pastes the 28-item list once, then a second pass — screenshots
each paired with a short caption — mostly in the same order as the list,
but not numbered against it. Most pairings above are unambiguous (the
caption text clearly restates the matching list item). Two are not, and
are marked "uncertain" rather than asserted:

- **image10.png** (caption: "increase box size like skip to next line to
  see what tyuped in") — placed in the docx right after item 6's theme
  (bigger edit-plan box) and before item 7's notification screenshot.
  Plausible match to item 6, not certain.
- **image22.jpg** — has no caption of its own in the docx; it sits
  immediately before a pasted excerpt of the guide's §4.2 "Reject Plan"
  text, with two other images (image18.jpg, image3.jpg, captioned
  "increase this small vague grey button all taks") right before it that
  clearly belong to item 10 instead. image22.jpg's position suggests it
  might illustrate item 12, but nothing in the docx confirms that.

## Ambiguous items — flagging rather than guessing

Per your instruction, these are described ambiguously enough that
resolving them would mean guessing your intent. Not fixed, not
interpreted above — just flagged here for you to clarify.

- **Item 12** — "the assurance box" isn't a label used anywhere in the
  app or the self-test guide. Unclear which UI element this refers to
  (the task-detail "Approve or reject this step" card? a different
  confirmation element?) and unclear whether "when rejected" means a
  rejected **plan** (§4.2) or a rejected **step** (§3.32/Reject Step).
- **Item 13** — "Add re run buttons" doesn't say where. Candidates that
  already have some form of this (Pipelines' existing "Trigger" button,
  Transforms' "Replay") vs. a genuinely new control somewhere else (Tasks?
  a failed step?) aren't distinguishable from the text alone.
- **Item 14** — cites "step 4.50," which doesn't exist in the guide (it
  only reaches §4.5, and §4.5 has 4 sub-steps, no decimal "4.50"). Can't
  tell if this means §4.5 generally, a typo for a specific sub-step, or
  something else. "Terminal response not correct" is also unclear on its
  own — which terminal, which command's output.
- **Item 15** — cites "4.54," same problem as item 14 (no such section;
  the guide's §4.5 has sub-steps 1–4, not a decimal 4.5.4). Possibly the
  same underlying observation as item 14 restated, possibly a different
  sub-step — can't tell which from the text.
- **Item 22** — "Settings page full customize it" is vague standing
  alone: unclear whether this means a broader/unspecified customization
  request beyond the timezone-dropdown ask that follows it in the same
  sentence, or whether it's just emphasis on that one fix.
