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
| 2 | in the backend; Date and time after profiling the data source is not correct. Add data source page closes sometimes own its own on tab switichin g | — | Bug | image5.jpg (first part only — no screenshot found for the "Add data source page closes on tab switching" part) | Closed (2026-08-19) — date/time part only, "closes on tab switching" not investigated this pass |
| 3 | pipeline feature also date and time is wrong does not match the date and time of the machine or the pc. | — | Bug | image12.jpg | Closed (2026-08-19) |
| 4 | In the axiom chat page there is no delete chat option for individual chat windows in the side panel | — | Feature | image15.jpg, image6.jpg | Open |
| 5 | remove the ask axiom button from the bottom left completely | — | Bug | image7.png | Closed (2026-08-19) |
| 6 | Axiom -> view progress -> each task should have bigger box in which we can edit anf review at once in the edit plan tab. | — | Design | image10.png (uncertain — see note below) | Closed (2026-08-19) |
| 7 | notification duration of every action or completion of the noptifications appearing on bottom left should be increased more smooth animation | — | Design | image4.png | Closed (2026-08-19) |
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
| 18 | 6.6 → dosent go to the conversation when clicked | §6.6 | Bug | image1.png | Closed (2026-08-19) |
| 19 | 8.3 → SQL execute and dry run not running for csv but it should as per the sel;f test guide from claude | §8.3 | Bug | image13.png | Closed (2026-08-19) — diagnosed as a guide error, not a product bug; see closure note |
| 20 | got logged out randomly maybe after 1 hour | — | Bug | none identified | Open |
| 21 | incidents banner does not go from dashboard notifications evenm after resolving and checking the incident. No clode button to clode the popup on investigate prompt tab | — | Bug | image2.png | Closed (2026-08-19) |
| 22 | Settings page full customize it. The timezone should be a drop down menu instead of manually typing timezone and after setting timezone it should work and should be correct according to machines timezone | — | Unclear | image14.png | Open |
| 23 | Onm first sign up some questionnaire is asked for more better understanding of user so store those answers in the user profile section in the setting tab | — | Feature | none identified | Open |
| 24 | Main change very important; PUT AXIOM in a sub folder in the dashboard with all the other employees. The side panel make it free free up some space. Like first i click on ai employees then i choose axiom and then the side panel changes accordingly and all axiom chat features appear in the side panel. Axiom is not the main employee is just the first on to be built so put it with all the other employees yet to come in a sub section. | — | Feature | none identified | Closed (2026-08-19) |
| 25 | double verification for changing the mail or slack url anbd invalid email task should be there when the email not verified. | — | Feature | image8.png | Open |
| 26 | approvals: check from different accounts for cicd action/ agent action | — | Untested | image19.png | Open |
| 27 | The self test guide has nothing on testing the CICD and automations feature please see into that too. | — | Feature | none identified | Open |
| 28 | ALL OF THIS HAS TO BE AUTOMATED the user upload data in the axiom chat is what we want and then the ai employee carries out all the remaining steps on its opwnm is what the main idea is just like claude code try to make the possible . make it chat friendly all the major working the user does while chatting with axiom if data needed axiom asks for it user uploads the data csv and axiom puts it in datasources and does profiling and all other steps on its own this is what we want fully automated process to reduce human effort. | — | Feature | none identified | Open |
| 29 | Nav items are not role-filtered — every logged-in user sees the identical sidebar regardless of role (a Viewer sees Team, Billing, Settings, and CI/CD listed exactly like an Owner does) and only hits a wall once they actually try to use something inside those screens. Found while investigating the sidebar's real role-gating for the 2026-08 IA restructure proposal — confirmed directly by reading `navItems.tsx`/`Sidebar.tsx`/`layout.tsx`, none of which do any role-based filtering; all real enforcement is one layer down, at the page/control level. Not fixed — logged only, per instruction. | — | Bug | none | Open |
| 30 | Governance's own **Audit Log** tab (a real, live tab inside the Governance screen) has the identical name as the sidebar's separate **Audit Logs** item (a stub page, unrelated screen) — a genuine naming collision between two different things. Already documented once, in passing, in `docs/SELF_TEST_GUIDE.md` §11's own note about this exact collision. Logged here as its own findings-index item per instruction — explicitly not renamed this session. | §11 | Design | none | Open |
| 31 | `run_quality_checks` accepts any `pipeline_id` string, including one that matches no real pipeline, and returns a false "100% passed, no active quality rules" result instead of erroring. Root cause: `QualityRuleEngine.run_checks()` (`modules/quality/rule_engine.py:92-103`) queries `QualityRule WHERE pipeline_id == pipeline_id` with no existence check first — zero rows matched looks identical whether the pipeline is real-but-ruleless or the ID is complete garbage. Found live, 2026-08-17, verifying the findings-8/9 argument-resolution fix: the `sync_profile_quality` task shape's own allowed-tools list (`TASK_SHAPE_ALLOWED_TOOLS`, `task_planner.py`) has no pipeline-discovery tool, so its final step's `pipeline_id` can never be resolved to a real value by either resolution tier — the task still reached `COMPLETED`, but the last step's "success" was hollow (zero rules actually evaluated). | — | Bug | T1_09_step3.png, T1_11_final_status.png (session scratchpad, not repo-committed) | Closed (2026-08-17) |
| 32 | Tier 2's LLM-based argument adaptation (`_adapt_step_args`, `task_executor.py`, added 2026-08-16) can silently substitute a real but *wrong* entity's ID when the entity the plan actually meant doesn't exist at all, and the step then reports success. Found live, 2026-08-17: a `diagnose_pipeline_failure` task deliberately targeting a nonexistent "Zephyr Cargo Manifest Pipeline" saw its `pipeline_id` placeholder replaced with the real ID of the unrelated "Sales Ingestion Pipeline" (visible in `prior_results` from the same task's own `list_pipelines` call) — the tool call succeeded against that wrong pipeline, and the task reached `COMPLETED` reporting on the wrong entity's run history, no error anywhere. Contrast with the same session's item 31/§Tier-1 behavior: Tier 1 (`_resolve_step_args`) is deliberately built to never guess between candidates and leave a genuine non-match untouched; Tier 2 has no equivalent guardrail — its prompt asks the LLM to *fix* the arguments, and a plausible-looking real ID from `prior_results` satisfies that instruction even when nothing in the task's own evidence actually supports it being the right one. | — | Bug | T4_04_status_check.png (session scratchpad, not repo-committed) | Closed (2026-08-17) |
| 33 | `detect_schema_drift` (agent tool, `ingestion_tools.py` → `SchemaProfiler.detect_drift()`) is classified `low` risk / `"view"` capability — reachable by every role including Viewer, no approval gate — but its real implementation overwrites `DataSource.schema_snapshot` and `last_profiled_at` and commits whenever drift is found (`schema_profiler.py:48-63`). A genuine, uncommented mutation sitting at the lowest risk tier. Also completely unverified: no automated test calls this tool, and no dated live-run passage names it individually anywhere in `SESSION_LOG.md`/`STATUS_TABLE.md`. Found during the 2026-08-18 product status audit (AXIOM tool-layer subagent pass). Not fixed — logged only. | — | Bug | 2026-08-18 audit | Open |
| 34 | `contract_service.validate_contract()` reads a source's real, live `schema_snapshot` as a flat `{"columns": [...]}` shape (`live_schema.get("columns", [])`), but `SchemaProfiler` always nests it per table (confirmed live 2026-08-17: `{"schema": {"main": {"columns": [...]}}}`). Every validation against a genuinely profiled source therefore finds `live_columns == []` and reports every single expected column as `schema.column_missing`, regardless of whether the schema actually matches. Originally found and documented in `docs/PRODUCT_AUDIT.md` (2026-08-04) as the identical bug class already fixed in `TransformGenerator._resolve_schema()`; re-confirmed still present and unfixed by direct code read during the 2026-08-18 audit. Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §2 (Governance — Contracts row); re-confirmed 2026-08-18 | Open |
| 35 | CI/CD's `run_schema_check()` (`services/cicd_tasks.py:53-86`) permanently no-ops: it imports `models.schema_snapshot.SchemaSnapshot`, a module that does not exist anywhere in this repo (confirmed: no such file), caught by its own `except ImportError` and silently returning `{"status": "skipped", ...}`. Schema drift has never once factored into any CI/CD risk score ever computed. Originally found in `docs/PRODUCT_AUDIT.md` (2026-08-04); re-confirmed still present and unfixed 2026-08-18. Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §3 item 6; re-confirmed 2026-08-18 | Open |
| 36 | Quality rule type `freshness` is declared in `QualityRuleEngine.RULE_TYPES` but has no dedicated evaluation branch anywhere in `_evaluate_rule()` — it falls through to the generic catch-all (`return {"passed": True, "message": f"Rule type '{rt}' not yet implemented"}`), meaning a `freshness` rule silently always passes with zero indication it isn't real. Originally found in `docs/PRODUCT_AUDIT.md` (2026-08-04); re-confirmed still present 2026-08-18 (grepped `rule_engine.py` for any `freshness`-specific branch — none exists). Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §3 item 10; re-confirmed 2026-08-18 | Open |
| 37 | `BusinessRules.create_rule()` validates `rule_type` correctly against its own `BUSINESS_RULE_TYPES` (8 types: reconciliation, kpi_sanity, etc.), but then delegates to `QualityRuleEngine.create_rule()`, which re-validates the same value against the *wrong* list (the base 8 quality-rule types: not_null/unique/etc.) and rejects it as "Unknown rule_type". No business rule of any type can be created through its own intended API today — the existing test suite works around this by inserting rows directly. Originally found in `docs/PRODUCT_AUDIT.md` (2026-08-04); re-confirmed still present by direct code read 2026-08-18. Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §2 (Business rules row); re-confirmed 2026-08-18 | Open |
| 38 | No general API rate limiting exists anywhere — confirmed by reading `main.py` in full, no `slowapi`/`Limiter`/rate-limit middleware of any kind. Password login (`POST /auth/login`) has zero brute-force protection: no failed-attempt counter, no lockout, no per-IP throttle, nothing but bcrypt's own cost factor — in sharp contrast to email-code login's real 4-layer Redis rate limiter. The chat endpoint (the single most expensive per-request cost driver in the app) has no per-minute abuse throttle either, only a monthly credit quota. Originally flagged in `docs/PRODUCT_AUDIT.md` (2026-08-04, items 12/13); re-confirmed still true by direct code read 2026-08-18. Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §3 items 12–13; re-confirmed 2026-08-18 | Open |
| 39 | `DataSource.connection_config` (`models/all_models.py:92`) is a plain `Column(JSON, nullable=False)` — real database passwords, API tokens, and (for Google Sheets) service-account private keys for every connected source are stored as plaintext JSON, no encryption at rest anywhere in the codebase (confirmed: no Fernet/encrypt wrapper found anywhere). Originally flagged in `docs/PRODUCT_AUDIT.md` (2026-08-04, item 11); re-confirmed still true 2026-08-18. Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §3 item 11; re-confirmed 2026-08-18 | Open |
| 40 | CI/CD's `run_sql_static_analysis()` scans only changed *filenames* and the commit *message* for risk keywords — never actual file/diff content. A real `DROP TABLE` in a changed file's body sails through undetected if the commit message doesn't happen to mention it. Separately, the post-deploy auto-rollback monitor's failure counters are only incremented by `POST /deployments/{id}/record-run`, which the real pipeline executor never calls — the "auto rollback on 2+ failures" safety net has no live trigger and has never once acted on real data. Both originally found in `docs/PRODUCT_AUDIT.md` (2026-08-04, items 6/7 — wait, these are items 6-7's siblings, see items 34-35 above for the schema-check twin); re-confirmed still present by direct code read 2026-08-18 (`GET /deployments/{id}/record-run` — no caller found anywhere outside `test_cicd_service.py`/`test_rbac.py`'s own direct calls). Not fixed — logged only. | — | Bug | `docs/PRODUCT_AUDIT.md` §3 items 7 & "Built fast, should be rebuilt properly"; re-confirmed 2026-08-18 | Open |
| 41 | `GET /api/v1/runs/{pipeline_id}` (`api/v1/runs.py:7`) appears to be a dead, duplicate route — it re-implements "pipeline run history" via `RunTracker.get_history()` (a documented pass-through to `DAGManager`, per `docs/context/GOTCHAS.md`), while the actually-used route for the same concept is `GET /pipelines/{pipeline_id}/runs`. No test, no doc citation, and no evident caller anywhere (frontend or otherwise) references `/api/v1/runs/{pipeline_id}` specifically. Found during the 2026-08-18 product status audit (backend-endpoint subagent pass). Not fixed — worth confirming genuinely orphaned before deleting. | — | Bug | 2026-08-18 audit | Open |
| 42 | `/billing`'s only cited live-verification (`docs/context/STATUS_TABLE.md`, Phase 17 step 3) describes an extensive Playwright pass against a plan-picker/upgrade-downgrade UI with a real `POST /change-plan` call — but the currently shipped `/billing` page (confirmed by direct file read, 2026-08-18) is a completely different, simpler read-only screen (a static "handled manually by the AXIOM team for now" notice, a usage-bars card, and a "Coming soon" checkout card) with no plan-picker, no Confirm button, and no `change-plan` call anywhere in the file. The only verification citation on record describes a feature that no longer exists in the shipped code; the current page has no verification event of its own. `docs/PRODUCT_AUDIT.md` (2026-08-04) already flagged this exact drift ("Billing (frontend): Fully working, but confirms doc drift"). Found independently during the 2026-08-18 audit (frontend-route subagent pass). Not fixed — a documentation-accuracy issue, not a product bug, but exactly the kind of stale "done" claim this audit exists to catch. | — | Design | `docs/PRODUCT_AUDIT.md` row "Billing (frontend)"; re-confirmed 2026-08-18 | Open |
| 43 | `docs/SELF_TEST_GUIDE.md` §1.3 tells a first-time tester: "open a browser and go to `http://localhost:3000`. You should land on a login page." The current code (`frontend/src/app/page.tsx`) renders the public marketing landing page unconditionally at `/` — there is no redirect to `/login`; `useIsAuthed()` only swaps CTA button labels. A tester following the guide literally would be confused at the very first step. Found during the 2026-08-18 product status audit (frontend-route subagent pass). Not fixed — a guide-accuracy issue. | §1.3 | Design | 2026-08-18 audit | Open |
| 44 | Two real, backend-wired frontend routes — `/cicd` and `/` (the marketing landing page) — have zero presence in `docs/SELF_TEST_GUIDE.md`, the only self-test walkthrough this product has; neither is mentioned even as a deliberate exclusion (contrast with Billing, which is explicitly named and reasoned about in §13). A tester who only ever follows the guide end to end would never be prompted to open either screen. Found during the 2026-08-18 product status audit (frontend-route subagent pass). Not fixed — a test-process gap, not a product bug. | — | Untested | 2026-08-18 audit | Open |

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

## Items 31 and 32 closed (2026-08-17, same day, follow-up work)

Both fixed within hours of being found — see `SESSION_LOG.md`'s 2026-08-17
entry for the full detail. Item 31: `run_quality_checks` and the same-shape
`BusinessRules.run_all()` now check pipeline existence before reporting a
result, instead of a bogus id and a real-but-ruleless pipeline looking
identical. Item 32: Tier 2's LLM adapt now has the same never-guess
guardrail Tier 1 already had — an adapted `_id`-shaped argument is only
accepted if it's a real id this task actually discovered AND that
discovery pool has exactly one member; 2+ real candidates or zero is
refused, reverting to the unresolved value so the step fails honestly
instead of silently retargeting onto the wrong real entity. Live-verified
for both a read-only shape (re-ran the exact item-32 repro, now fails
honestly) and a mutating shape (`sync_source` against a nonexistent
source with 2 real candidates in the pool — confirmed via direct DB read
that neither real source was touched).

## Batch 1 closed (2026-08-19) — navigation and removals

Items 24, 5, 6, 7, worked in that order per an explicit 4-batch plan
covering all remaining Open items (batches 2-4 not yet started as of this
note). All frontend-only, live-verified via Playwright against the real
running dev server, no backend touched.

- **Item 24**: completed the 2026-08 IA restructure that previously only
  moved Chat/Tasks into AXIOM's own sidebar domain — Data Sources, Data
  Catalog, Pipelines, Transforms, Quality, Incidents, Governance,
  Automations, and CI/CD now move there too. Approvals deliberately stays
  in the Workspace sidebar (CI/CD deployment approvals are webhook-driven,
  not AXIOM-initiated — burying them behind an AI employee would make them
  unreachable for their main use case), a correction to the original
  finding's own literal request. `isAxiomDomain()`'s route list expanded
  to match; live-verified a hard-reload deep link into `/sources` and
  `/cicd` both paint the correct sidebar immediately, `/approvals` stays
  Workspace-mode.
- **Item 5**: `AxiomFab.tsx` deleted entirely (component, its export, its
  render site in the app shell layout, both CSS rule blocks) — not hidden.
  Confirmed a 0 count for the element on a real logged-in page.
- **Item 6**: the plan-edit view's step-description field is now a
  multi-line textarea (was a single-line input) and the tool_args box
  grew from a 60px to a 160px minimum height. Live-verified against a
  real Draft Plan task with a deliberately long description — wraps
  across multiple visible lines instead of being cut off.
- **Item 7**: toast auto-dismiss raised 4000ms → 6000ms, entrance
  animation switched to a smoother cubic-bezier curve, and toasts now get
  a real fade+slide exit transition instead of an instant unmount (only
  the entrance had any animation before). The finding's own text says
  "bottom left" — the toast container is and always has been bottom-
  *right* (confirmed in code and screenshot); read as a misremembering in
  the original notes, not a real position bug, and not moved.

The dead "Production" workspace-selector row (a related `docs/PRODUCT_AUDIT.md`
finding, never given its own number here) was explicitly folded into item 1
rather than fixed here — item 1 is being proposed, not built, before any
change to that row.

`docs/SELF_TEST_GUIDE.md` updated alongside: §2.2, §3.12, §7, §8, and §11
now correctly describe entering AXIOM's domain to reach the 9 relocated
screens, instead of the stale "in the left sidebar, click X" instructions
that assumed the old, narrower Chat/Tasks-only domain. Screenshots
deliberately not retaken (deferred to the post-restyle pass, per explicit
instruction) — only the text describing what to click was corrected.

## Batch 2 closed (2026-08-19) — display bugs

Items 2/3, 21, 18, 19, worked in that order. All frontend-only except
item 19 (a documentation-only fix, no code changed). Every code fix
live-verified via Playwright against the real running dev server and app,
not just a green `tsc`/build.

- **Items 2/3**: root-caused to the API emitting three distinct raw
  timestamp shapes (see the new `docs/context/GOTCHAS.md` entry for the
  full detail) with no UTC marker on two of them - 17 of 22 frontend
  `new Date(...)` call sites silently read a UTC value as local time.
  New `frontend/src/lib/dates.ts` (`parseApiDate`/`formatApiDate`/
  `formatApiDateOnly`), wired into all 20 real call sites (2 were
  deliberately out of scope - `chat/page.tsx`'s optimistic local
  timestamps, not parsed API strings). Verified via a plain assertion
  script (no test framework exists for this frontend) - 13/13 passed,
  including that the two genuinely timezone-aware CI/CD fields do not
  get corrupted by a second appended `Z`. Live-verified one site per
  shape against real DB values, all exactly the expected IST (+5:30)
  offset, including a real CI/CD commit inserted and removed purely for
  this check.
- **Item 21**: two independent bugs. `getOpenIncidents()` sent no
  `status` filter despite its name, so a resolved incident could sit at
  the front of "open incidents" data and the Dashboard's health banner
  never cleared even after resolving it - fixed with a real
  `status=open` param, and the Incidents screen (which genuinely needs
  full history) switched to the new unfiltered `getIncidents()` instead.
  The Dashboard/Incidents query-key split ("open-incidents" vs
  "incidents") turned out to be *correct* once the underlying bug was
  fixed, not itself the landmine - the two screens now legitimately want
  different data; what needed fixing was that resolving an incident on
  one screen didn't invalidate the other's cache, now fixed. Added a
  dismiss (X) control to the banner, persisted per-incident-id via
  localStorage, independent of actually resolving the incident.
  Live-verified: resolved a real incident, confirmed the Dashboard
  banner correctly moved to the next genuinely-open one (matching a
  direct API call exactly); confirmed the Incidents screen still shows
  resolved incidents (no regression); confirmed dismiss hides the banner
  and survives a hard reload.
- **Item 18**: the Dashboard's AXIOM Activity rows navigated to a bare
  `/chat` with no session context, always landing on a blank new thread.
  Now navigates with `?session=<real id>`, consumed once on mount by the
  existing `selectSession()` (already used by the in-chat session list -
  no new selection logic), then stripped from the URL. Live-verified
  with a real chat session: clicking the row loaded the correct real
  conversation history, not a blank thread.
- **Item 19**: diagnosed, not a product bug - `SqlRunner` only supports
  `postgres`/`mysql` source types by design; a CSV source (the only kind
  this guide's credentials-free walkthrough can provide) correctly gets
  a clean, honest rejection (`SqlRunner does not support source type
  'csv'.`), confirmed live. `SELF_TEST_GUIDE.md` §8.3 was the actual bug
  - it claimed real row-data results against a CSV source, which was
  never true. Corrected in place; no application code changed for this
  item.

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
