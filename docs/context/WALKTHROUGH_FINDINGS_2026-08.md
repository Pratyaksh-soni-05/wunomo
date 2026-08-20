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
| 1 | After first sign up of user or after every login it asks to choose workspace remove that whole thing i dont wanna choose a workspace we enter into the workspace of the last login and then in the dashboard we can toggle the workspaces but remove that pop up at the start of every login to choose workspace we directly login into the dashboard of last logged in workspace. | — | Feature | image16.jpg | Closed (2026-08-19) |
| 2 | in the backend; Date and time after profiling the data source is not correct. Add data source page closes sometimes own its own on tab switichin g | — | Bug | image5.jpg (first part only — no screenshot found for the "Add data source page closes on tab switching" part) | Closed (2026-08-19) — date/time part only, "closes on tab switching" not investigated this pass |
| 3 | pipeline feature also date and time is wrong does not match the date and time of the machine or the pc. | — | Bug | image12.jpg | Closed (2026-08-19) |
| 4 | In the axiom chat page there is no delete chat option for individual chat windows in the side panel | — | Feature | image15.jpg, image6.jpg | Closed (2026-08-19) |
| 5 | remove the ask axiom button from the bottom left completely | — | Bug | image7.png | Closed (2026-08-19) |
| 6 | Axiom -> view progress -> each task should have bigger box in which we can edit anf review at once in the edit plan tab. | — | Design | image10.png (uncertain — see note below) | Closed (2026-08-19) |
| 7 | notification duration of every action or completion of the noptifications appearing on bottom left should be increased more smooth animation | — | Design | image4.png | Closed (2026-08-19) |
| 8 | in step #3.30 in self test guide. After running the completion button is not coming back | §3.30 | Bug | image17.jpg (shared with item 9) | Closed (2026-08-17) |
| 9 | 3.30 → 3.32 steps in self test guide are not working | §3.30–3.32 | Bug | image17.jpg (shared with item 8) | Closed (2026-08-17) |
| 10 | increase all button sizes make them more aesthetic easy to click and only text is written when cursor hovers on top then a greay button boundary appears just like claude or any other website | — | Design | image21.jpg, image18.jpg, image3.jpg | Open |
| 11 | 'help' → should give error and not generate any plan in step 4.1 in self test guide but it is working and still appearing in the task list with plan approval | §4.1 | Bug | none identified | Open |
| 12 | when rejected the assurance box is not appearing back again | — | Unclear | image22.jpg (uncertain — see note below) | Open |
| 13 | Add re run buttons | — | Unclear | none identified | Closed (2026-08-19) |
| 14 | step 4.50 in self test guide Terminal response not correct | §4.50 (as written) | Unclear | image20.png | Open |
| 15 | 4.54 check terminal output again | §4.54 (as written) | Unclear | image9.png | Open |
| 16 | in step 6.1 in self test guide cards not reloading after refresh | §6.1 | Bug | none identified | Closed (2026-08-17) |
| 17 | 6.3 → 6.4 check from different accounts | §6.3–6.4 | Untested | image11.png | Open |
| 18 | 6.6 → dosent go to the conversation when clicked | §6.6 | Bug | image1.png | Closed (2026-08-19) |
| 19 | 8.3 → SQL execute and dry run not running for csv but it should as per the sel;f test guide from claude | §8.3 | Bug | image13.png | Closed (2026-08-19) — diagnosed as a guide error, not a product bug; see closure note |
| 20 | got logged out randomly maybe after 1 hour | — | Bug | none identified | Open |
| 21 | incidents banner does not go from dashboard notifications evenm after resolving and checking the incident. No clode button to clode the popup on investigate prompt tab | — | Bug | image2.png | Closed (2026-08-19) |
| 22 | Settings page full customize it. The timezone should be a drop down menu instead of manually typing timezone and after setting timezone it should work and should be correct according to machines timezone | — | Unclear | image14.png | Closed (2026-08-19) |
| 23 | Onm first sign up some questionnaire is asked for more better understanding of user so store those answers in the user profile section in the setting tab | — | Feature | none identified | Closed (2026-08-19) |
| 24 | Main change very important; PUT AXIOM in a sub folder in the dashboard with all the other employees. The side panel make it free free up some space. Like first i click on ai employees then i choose axiom and then the side panel changes accordingly and all axiom chat features appear in the side panel. Axiom is not the main employee is just the first on to be built so put it with all the other employees yet to come in a sub section. | — | Feature | none identified | Closed (2026-08-19) |
| 25 | double verification for changing the mail or slack url anbd invalid email task should be there when the email not verified. | — | Feature | image8.png | Closed (2026-08-19) — Slack double-verification and the unverified-email notice only; changing to a NEW email is a separate, unbuilt piece, see closure note |
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
| 45 | The API emits three different raw timestamp string shapes for the same conceptual "when did this happen" value, depending on which serialization path produced it: a bare naive string with microseconds (`"2026-08-16 09:46:54.933113"`), a bare Pydantic-serialized naive string (`"2026-08-16T09:46:54.933113"`), and a genuinely tz-aware ISO string with trailing `Z` (CI/CD models only, per Hard Rule 3's documented exception). The frontend now normalizes all three correctly via `frontend/src/lib/dates.ts` (built for items 2/3, closed 2026-08-19), but any consumer hitting the API directly — a script, an integration, a future mobile client — gets the raw inconsistency with no way to distinguish "naive, needs UTC assumed" from "already aware" except by knowing which endpoint it came from. Found while building items 2/3's fix, 2026-08-19. Not fixed — an API-contract problem, not urgent, explicitly out of scope for this session. | — | Bug | none | Open |
| 46 | `Task.originating_session_id` (`models/all_models.py:465`) exists in the model and its own migration specifically to trace a task back to the chat session it was spawned from, but no code path ever sets it — confirmed by grepping the entire backend: `create_task()` (`api/v1/tasks.py:308`) never assigns it, and the frontend's "+ Start a Task" flow (`TaskCreateModal.tsx` → `createTask()`) never sends a session_id in the first place. Every task in this codebase has `originating_session_id = NULL` regardless of whether it was actually started from within a chat conversation. Found 2026-08-19 while investigating item 4 (delete-conversation) — needed to confirm whether deleting a session could orphan a task; it can't, because none are actually linked. Sized as small and tacked onto the end of batch 3 rather than left open, per review feedback. | — | Bug | none | Closed (2026-08-19) |
| 47 | `services/auth_service.py`'s email-code rate limiter (`MAX_REQUESTS_PER_IP_PER_HOUR = 20`, key `otp:ip:{ip}`) is real Redis state shared across an entire pytest session with no per-test-file reset fixture found. Running a sufficiently broad `-k` selection that happens to pull in several files calling `POST /auth/email-code/request` (e.g. `-k "auth or settings"`) can exhaust the 20/hour budget purely from the suite's own combined request volume, then spuriously fail `test_email_code_auth.py::test_resend_cooldown_blocks_immediate_second_request` and `::test_rate_limit_bookkeeping_is_symmetric_for_nonexistent_emails` — both pass cleanly in isolation (`pytest tests/test_email_code_auth.py`, 11/11) and only fail when combined with enough sibling tests to burn the shared quota first; confirmed live by reading `otp:ip:127.0.0.1` from Redis directly after a failing run (23, over the 20 cap) and after a clean isolated run. Found 2026-08-19 while running the full auth/settings suite to verify item 25's changes. **Fixed 2026-08-19 (batch 4)** — see closure note below. | — | Bug | none | Closed (2026-08-19) |
| 48 | `STATUS_TABLE.md`'s already-documented "Freshness checker creates duplicate open incidents" Known-broken row (`_check_freshness()` in `services/tasks.py`, runs every 15 min via Celery beat, creates a brand-new `Incident` row every tick a source is still stale instead of checking for an already-open one first) is not a stale historical note — it is live and actively still running right now. Found while investigating the "Email Code Verify Corp" QA tenant for possible deletion (2026-08-19): that tenant's one `DataSource` ("Sales_Data") has sat unprofiled since 2026-07-22, and `_check_freshness()` has generated one new "Stale data: Sales_Data (N.Nh overdue)" incident every ~15 minutes since. Trajectory, this one tenant, same day: **7 (STATUS_TABLE's original note) → 324 → 329 (first 2026-08-19 check) → 355 (re-check during the item 53 escalation, same day)**. Root cause unchanged from the original entry: `services/tasks.py`'s `_check_freshness()`, unconditional `db.add(incident)` inside `if hours_since > sla_hours:`, no dedup query against existing open incidents for the same `affected_assets`. **Escalated 2026-08-19 — see item 53: this is one of at least 242 genuinely distinct tenants exhibiting the identical pattern simultaneously (before counting ~97 more that share a single leftover test-fixture name — see item 53's correction), not an isolated dead-tenant curiosity.** Not fixed — logged only, per instruction; the fix belongs with the original Known-broken row, not as new scope here. | — | Bug | none | **BLOCKING (escalated 2026-08-19)** |
| 49 | Same bug as item 48, additional live confirmation on a second tenant. Found 2026-08-19 auditing Phase 0 of the frontend upgrade brief's demo-tenant question (`demo@axiom-yc.ai` / tenant "AXIOM YC Demo", id `00c413dd-ed73-42f1-995c-40f121490ee6` — the tenant Phase 7's screenshots are meant to come from): `incidents` for this tenant had 111 rows at first check, 109 `OPEN` / 2 `RESOLVED` — all near-identical `"Stale data: Sales Orders (N.Nh overdue)"` / `"Stale data: Employee Records (N.Nh overdue)"` pairs. Trajectory, this one tenant, same day: **109 → 123 (Phase 4 dashboard audit re-check) → 151 (re-check during the item 53 escalation, same day)** — confirmed each time by a tenant-scoped direct query, not an estimate. Same root cause as item 48 (`_check_freshness()` in `services/tasks.py`, no dedup against an already-open incident for the same asset) — logged separately only because it hits the specific tenant the frontend brief's Phase 7 screenshots depend on: an Incidents-screen capture taken today would show duplicate rows, not the one clean incident `docs/SELF_TEST_GUIDE.md` §7.1 describes. **Escalated 2026-08-19 — see item 53: correcting an earlier same-day conflation.** An earlier draft of item 53 mistakenly reported this tenant's own count as 51,864 — that number is the *system-wide* total across all tenants, not this tenant's; this tenant's real, own count is 151, tracked separately here. Not fixed — logged only, per instruction; rows deliberately left in place (deleting them to clean up a screenshot would hide the bug and let it keep regenerating). The Dashboard's "Open Incidents" KPI correctly shows the real, current count with no frontend-side filtering or dedup. Fix belongs with item 48's, not as new scope here. | — | Bug | none | **BLOCKING (escalated 2026-08-19)** |
| 53-correction | **The escalation number, corrected and led with: 17,940 `OPEN` incidents across 242 genuinely distinct tenants** (excluding a confirmed leftover test-fixture cohort — see item 56 for that defect on its own). This replaces item 53's original headline figure (51,894 across 339 tenants), which was accurate as a raw query but misleading as *the* escalation number without checking what it was made of. **What rules out a single misconfigured tenant, stated first because it's the point of this correction**: no tenant dominates this figure — the largest contributor excluding the fixture cohort, "Pipelines Verify Co," is **9.6%** of the 17,940 total, and growth is spread across all 242 tenants rather than concentrated in one. That's what makes this a systemic bug, not a tenant-specific one. Growth rate excluding the cohort, same 6-hour window as item 53's original check: 389, 313, 312, 312, 312, 78 rows/hour. **Filed as its own row per instruction, not buried inside item 53.** Full investigation: item 53's original 65.5%-from-one-tenant claim traced to "Run Status Test Corp," which turned out to be **101 distinct tenant rows sharing one pytest-fixture name**, not one tenant (see item 56 — that's a separate defect, the test suite itself, logged on its own so it isn't closed automatically whenever the freshness bug is fixed). 97 of those 101 rows currently have `OPEN` incidents, summing to 33,954 — checked and ruled out that any one of them loops faster than another (largest individual tenant ID: 504 `OPEN`, same order of magnitude as every other affected tenant system-wide) — the total is large only because there are ~100 of them. **Including the fixture cohort** (the true current row count in the table, for reference, not the escalation number): 51,894 `OPEN` across 339 tenants, growing ~700–875 rows/hour including the cohort's contribution. **Per explicit instruction, none of the 33,954 rows were deleted** — not this branch's call, real evidence of the bug's true reach, and deleting them would only let them regenerate. `STATUS_TABLE.md`'s Known-broken row updated with both figures, led with the same corrected number. **Phase 7 impact (2026-08-19), a second one beyond item 55's Incidents-screen block:** the Dashboard's "Open Incidents" KPI card also surfaces this bug directly — real, accurate, not truncated like Incidents' `count` field (item 55), but a static landing-page screenshot is a different kind of artifact than a live number: it outlives the moment it was taken. A Dashboard capture showing "169 Open Incidents" today reads as "109" a week ago and will read as some other number next week — frozen into a public asset, it stops being a live status and starts being a permanent, misleading claim about what this two-source demo tenant "normally" looks like. **A landing-quality Dashboard capture is blocked on this fix, same as Incidents is on item 55** — the Dashboard capture itself is fine for `docs/self_test_assets/` (documenting real current state, which is exactly what that directory is for) and held from `public/screenshots/` until the freshness-checker bug closes. | — | Bug | none | **BLOCKING (escalated/corrected 2026-08-19)** |
| 56 | **Test-infrastructure defect, independent of items 48/49/53 — the freshness-checker bug and this one are separate and both real; fixing one doesn't fix the other.** The pytest fixture behind "Run Status Test Corp" writes a permanent, never-torn-down tenant row to the shared dev database on every test run, not a scoped/cleaned-up one. Found 2026-08-19 while investigating item 53's original "one dominant tenant, 65.5%" claim (see item 53-correction). Evidence: `SELECT DISTINCT id FROM tenants WHERE name='Run Status Test Corp'` returns **101 distinct tenant rows**, created repeatedly 2026-07-14 through 2026-08-18 — over a month of accumulation with zero cleanup between runs. Every one of the 3 sampled directly has the identical shape: a synthetic `runstatus-<hex>@example.com` user (e.g. `runstatus-468a4323@example.com`), and exactly one `DataSource` named `"missing file source"`, profiled once at creation and never touched again. This is the same failure class `docs/context/GOTCHAS.md` already documents for other `*_Test Corp`/`*_Verify Co`-style fixtures (`Usage Test Corp`, `Reasoning Test Corp`, etc. — 222 of 348 all-time `gemini`-labeled `llm_usage_events` rows previously found to be phantom test writes from an analogous pattern) — this is a new instance of a known, recurring class of test-suite hygiene gap, not a one-off. Real-world consequence beyond the incidents table specifically: every test run that exercises this fixture leaves a permanent tenant, user, and data source in a database other sessions and other tests also read from — the 51,864-figure escalation in item 53 is partly an artifact of this gap, not purely of the freshness-checker bug. Not fixed — backend/test-infrastructure, out of this branch's scope; logged on its own, separate from item 53, specifically so it doesn't get marked closed the day someone fixes `_check_freshness()`'s dedup (that fix stops these 97 tenants from accumulating *more* incidents, but does nothing about the 101 leftover tenant rows themselves, or about the fixture continuing to create a 102nd, 103rd, etc. on every future test run). Real fix needs test-suite-side teardown (a fixture that deletes what it creates, or reuses a single fixture tenant across runs instead of minting a new one every time) — a decision for whoever owns the test suite, not made here. Per explicit instruction, none of the 101 tenant rows or their incidents were deleted. | — | Bug | none | Open |
| 57 | **Analytics is a live, reachable nav item leading to an empty stub screen — not a styling issue, but flagged now specifically because Phase 7 is about to screenshot the product for real, and this needs to be known before anything gets captured, not discovered in a screenshot afterward.** `analytics/page.tsx` renders only `<StubPage title="Analytics" />` (no `phase` prop passed), which currently shows: an icon, the heading "Analytics", and the body text *"This screen is a routable stub for now — real content lands in a later phase."* No chart, no data, no real content of any kind — confirmed by direct file read and a live screenshot during Phase 6 items 3-5's audit, both themes. The nav item itself is fully live and reachable (sidebar → Analytics, both workspace-domain sessions checked have it), so a normal user — or a screenshot pass — can land here with zero indication in the nav itself that it's unfinished. Found 2026-08-19 during Phase 6 items 3-5's screen-by-screen pass. Not fixed — out of this session's scope (building the screen is real feature work, not a token/styling fix); logged specifically so Phase 7's screenshot pass excludes or flags it deliberately rather than accidentally capturing an empty stub as if it were a finished screen. | — | Design | `p6_analytics_light.png`, `p6_analytics_dark.png` (session scratchpad, not repo-committed) | Open |
| 58 | `docs/SELF_TEST_GUIDE.md` instructed clicking several row-action buttons by their visible text label, but Phase 6 part 2's density conversion (this same session, earlier) turned every one of those into an icon-only button — the label was gone, only a `title`/`aria-label` tooltip remained. Found 2026-08-19 while auditing the guide's colour references (a separate, narrower task) — a different defect class (interaction/affordance drift, not colour). **Fixed same-day, in the same session** (escalated from "flag it" to "fix it now" per explicit instruction: this session's own Phase 6 work broke the guide, so it closes it too). Every affected instruction now names the icon (shape + tooltip text) and its position in the **Actions** column, rather than a label that no longer renders: §2.3/§2.4 (Sources — Profile icon, Sync icon, Delete behind the ⋮ overflow); §3.6/Part A's "also try" note (Pipelines — Trigger/Activate/Pause icons, Delete behind ⋮); §3.11 (Quality — Run Checks icon, found during this fix pass, not in the original discovery); §7.4 (Incidents — Resolve icon); §9.6 (Settings API Keys — Revoke behind ⋮); §10 (Approvals — Approve icon, Reject behind ⋮); §11.3 (Governance Contracts — Validate icon). One general note added at its first occurrence (§2.4, the first table this guide touches) explaining the standing rule — frequent/non-destructive actions are inline icons, destructive/irreversible ones live behind the ⋮ overflow — so later sections can reference it instead of re-explaining. The original discovery's speculation about CI/CD and Team also needing fixes was checked and was wrong: neither screen has a `docs/SELF_TEST_GUIDE.md` section at all (matches item 44's already-documented gap), so there was nothing to fix there. Full sweep confirmed clean via repo-wide grep for the old label-click phrasing after the edit. | §2.3, §2.4, §3.6, §3.11, §7.4, §9.6, §10, §11.3 | Design | none | Closed (2026-08-19) |
| 50 | `RecentRunsCard.tsx` (Dashboard's "Recent Pipeline Runs" card) carried each run's status (success/failed/running) by the colour of a `.status-dot` alone — no adjacent text or icon stated it. A colourblind user, or anyone viewing a greyscale render, could not distinguish a failed pipeline from a successful one on this card. Found 2026-08-19 during the frontend brief's Phase 1b colour-alone audit (checking every `Badge`/`status-dot` call site — all 37 `Badge` usages already carry a text label; this was the one bare `status-dot` that didn't). `NotificationsPanel.tsx` has the same shape but is confirmed dead code (never imported/rendered — see `SELF_TEST_GUIDE.md`'s known-issues list), so not counted as a live instance. **Fixed 2026-08-19 (Phase 2)** — added a text label ("Succeeded"/"Failed"/"Running") beside the dot, colour-matched to it, same pattern the `Badge` components already use elsewhere. Also removed `StatusDot` (the unused component Badge.tsx exported alongside `Badge`, never actually imported anywhere) so it can't get picked up as "the" status-indicator pattern instead of the text+colour one that actually ships. | — | Bug | none | Closed (2026-08-19) |
| 51 | `Topbar.tsx`'s account-menu trigger (the initials avatar, top right of every screen) is a `<div onClick>`, not a `<button>` — no `role`, no accessible name, and not reachable by keyboard (`Tab` skips it entirely; there's no way to open the account dropdown without a mouse). Same defect class as item 50 (a real interactive control missing the markup that makes it actually usable), found 2026-08-19 during the Phase 2 button-tier audit while checking why this element stayed 30px when its neighboring topbar icon buttons grew to 44px — it never went through `.btn`/`Button` in the first place. **Fixed 2026-08-19 (Phase 5)** — real `<button>` with `aria-label`, `aria-haspopup="menu"`, `aria-expanded`, keyboard-reachable by construction; resized 30px to 44px, matching its neighboring topbar icon buttons. | — | Bug | none | Closed (2026-08-19) |
| 52 | The chat composer's textarea (`MessageThread.tsx`) never actually grows with content, despite its own CSS declaring `min-height: 40px; max-height: 120px` — an auto-grow range with no JS behind it (`rows={1}`, static, never updated; no `scrollHeight`-driven resize anywhere in the file). Typing multi-line input doesn't expand the box; it silently scrolls the extra lines out of view inside the fixed 40px frame. Found 2026-08-19 while checking whether the Send button (`.btn-anchored`, 44px) stays correctly aligned as the field grows for the frontend brief's Phase 6 chat review — it does (nothing moves, because nothing grows), but that's the wrong finding: verified live with 3 and 6 lines of real input (`textareaHeight` stayed exactly 40px in both cases while `textareaScrollHeight` reached 51px and 102px), and a 6-line draft screenshot shows only the last ~3 lines visible, the rest scrolled out of sight with no visible scrollbar cue. A user reviewing a longer message before sending can't see what they wrote without manually scrolling inside a 40px box. **Fixed 2026-08-19 (Phase 6 part 2)** — added a `useEffect` keyed on `draft` that resets the textarea's inline height to `40px` before measuring `scrollHeight` (so it shrinks back down as well as grows), then sets height to `min(scrollHeight, 120)px`; added `overflow-y: auto` to `.chat-composer-box textarea` so a scrollbar appears once content exceeds the 120px ceiling. Verified live: rest = 40px, 3 lines = 51px, 8 lines clamps to 120px with `overflow-y: auto` and `scrollHeight` 136px (so the extra content scrolls inside the box instead of being clipped invisibly), clearing the draft returns it to 40px. | — | Bug | none | Closed (2026-08-19) |
| 53 | **See row "53-correction" directly below for the corrected, lead-with figure (17,940 / 242 tenants), and item 56 for the separate test-fixture defect this row's "Run Status Test Corp, 65.5%, one tenant" framing turned out to be — it's 101 distinct tenants sharing one leftover fixture name, not one tenant, and that's its own bug, not part of this one. This row is kept verbatim as the original finding.** **ESCALATION, not a new bug — items 48/49's root cause is not an isolated dead-tenant curiosity, it is an active, unbounded, system-wide write loop.** Found 2026-08-19 while screenshotting the Incidents screen for the Phase 6 part 2 density work: a first, tenant-unscoped query (mistake — see item 49's correction note) returned 51,864 total incidents and was initially misattributed to the single `demo@axiom-yc.ai` tenant. Re-run correctly scoped: **51,719 `OPEN` / 95 `INVESTIGATING` / 225 `RESOLVED` system-wide, across 339 distinct tenants that currently have at least one `OPEN` incident** (of 15,951 tenants total in this dev DB — overwhelmingly leftover test-suite tenants, the same accumulation pattern documented in `docs/context/GOTCHAS.md`). Every one of those 339 tenants is independently exhibiting items 48/49's exact bug (`_check_freshness()` in `services/tasks.py`, no dedup against an already-open incident for the same stale asset, ticking every 15 min via Celery beat) simultaneously, right now. The single largest contributor is tenant **"Run Status Test Corp" at 33,857 `OPEN` incidents — 65.5% of the entire system-wide total, alone** — a leftover test tenant with a permanently-stale source that has apparently been ticking, unattended, for a very long time; the next-largest are "Pipelines Verify Co" (1,716) and "Simulation Corp" (1,006). Measured real growth rate over the 6 hours before this check (hourly buckets of new `OPEN` rows, system-wide): 175, 874, 701, 700, 700, 700 — roughly 700–875 new rows/hour in steady state, i.e. **this dev database's incidents table is growing by roughly 700+ rows every hour, right now, unattended, with zero cap.** This is the same root cause as items 48/49, confirmed identical, just measured at its true scope for the first time rather than one tenant at a time. **Severity escalated from "flagging only" to BLOCKING**: this is not a documentation gap, a screenshot problem, or something a frontend fix can address — it is live, unbounded, production-shaped write-loop code (`services/tasks.py:_check_freshness()`) that will keep consuming DB storage and (per the already-closed item 50's sibling wiring) generating downstream volume indefinitely until `_check_freshness()` is given a real dedup check before `db.add(incident)`. **Flagged explicitly for the next backend-focused session** — this frontend/design-system session did not and should not touch `services/tasks.py`; see `docs/context/STATUS_TABLE.md`'s "Freshness checker creates duplicate open incidents" Known-broken row (now marked Severity: Critical / BLOCKING) and `docs/context/SESSION_LOG.md`'s 2026-08-19 entry for the explicit handoff. Not fixed — out of this branch's scope by design, not by oversight. | — | Bug | none | **BLOCKING (escalated 2026-08-19) — flagged for backend session, see STATUS_TABLE.md + SESSION_LOG.md** |
| 54 | `tr.selected`'s dark-mode near-black-ceiling implementation (`components.css:291-294`, written this session as part of Phase 6 part 2) does not reliably read as "selected" — verified live, not assumed. `--accent-subtle-bg` in dark mode is defined as `var(--surface-hover)` (`tokens.css:379,446`), the identical token `tbody tr:hover td` already uses — so a selected row's fill is byte-identical to a merely-hovered row's fill, not just visually close. The inset-border meant to carry the distinguishing signal per brief §4's own rule ("no subtle fill tint reaches 3:1 — rely on a solid border instead") computed to `--accent-subtle-border: #26262a` against a `#1A1A1D` selected background and `#121214` page surface — measured contrast **1.15:1 and 1.24:1** respectively, nowhere near the 3:1 a perceptible UI-state border needs, and effectively invisible at table scale (confirmed by a zoomed screenshot of a `.selected` row against an unselected one — no visible difference). The rule's own reasoning ("fill can't reach 3:1 on near-black, so lean on a border instead") was applied without checking the border itself also fails 3:1, on the same near-black surfaces — a border drawn from the same neutral-grey family as the surface around it is still a low-contrast-gradient signal, just moved from fill to border. Found 2026-08-19 verifying Phase 6 part 2's own tr.selected requirement. **Fixed 2026-08-19 (same session)** — replaced the top/bottom neutral-grey inset border with a **3px solid `--brand-blue` bar on the row's leading edge only** (`tr.selected td:first-child { box-shadow: inset 3px 0 0 var(--brand-blue); }`), plus `color: var(--text-primary)` on the row's text; `--accent-subtle-bg` kept as the fill, per instruction, since the bar (a shape, not a contrast gradient) is what actually carries the signal now, not the fill. New `--brand-blue` token added (`tokens.css`, tracks `--focus-ring` the same way `--accent-border` already does — `#0056FF` light / `#2277FF` dark, both already real-contrast-verified elsewhere in this file). Verified live at real 100% zoom (not zoomed in), a genuinely `:hover`-ed row screenshotted side by side with a `.selected` row in both themes: the two are now unambiguously distinct — hover shows only the flat grey lift, selected shows the grey lift plus a clearly visible blue edge bar. Brief §4 amended with the corrected rule (a border must be a real accent colour, never a neutral grey from the same near-black family, and shaped to stand apart from the surface's existing structural lines) — this row is cited there as the evidence. **Independent precedent found later the same session** (Phase 6 items 3-5's audit): the Tasks detail page's failed-step banner (`tasks/[id]/page.tsx:293`) already used a left-edge coloured bar, driven by a dynamic `var(--${reason.variant})` reference, built before this fix existed — someone independently reached the same shape-over-tint answer for a different problem (a failure-reason marker, not a selection state). Cited in brief §4 alongside this row as evidence the corrected rule is the natural fix, not a patch after two failed attempts. | §4 | Bug | none | Closed (2026-08-19) |
| 55 | **Frontend-only bug, distinct from item 53's backend cause — logged separately so fixing the backend doesn't leave this invisible.** `GET /api/v1/incidents/` (`backend/api/v1/incidents.py:39-49`) has a hardcoded `limit: int = 50` query param default, no pagination controls anywhere in the frontend (`getIncidents()`, `src/lib/api.ts:301`, never passes one), and its response's own `"count"` field is computed as `len(incidents)` — i.e. it always equals whatever the truncated page returned, never the true total. Found 2026-08-19 alongside item 53. The Incidents screen shows only the newest 50 rows with nothing on screen indicating more exist — no "50 of N" count, no pager, no "load more" — and the API's own `count` field actively reinforces the lie by reporting exactly 50 as if it were the whole answer. This is real independent of item 53's severity: even with a small, sane incident count, an endpoint whose `count` field silently means "count of what I decided to send you," not "how many exist," is a bug — any other consumer trusting that field is being actively misled, not just under-informed. Not fixed — logged only, out of this session's scope (density work, not pagination). Real fix needs two matched parts: a real paginated endpoint (`count` from a separate `SELECT count(*)` against the full query, not `len(page)`; a real `offset`/cursor param) plus a frontend pager or a stated "showing 50 of N" — fixing only one half (e.g. bumping `limit`) doesn't fix the contract, it just moves the truncation point. **Phase 7 impact (2026-08-19): the Incidents screen is excluded from this rollout's screenshot pass entirely because of this bug** — a capture taken today (demo tenant real count: 163 `OPEN`) would show 50 rows with the API's own `count` field stating "50" as if that were the total, an actively false claim, not just an incomplete one. Screenshotting a screen that states something false would put that lie into `docs/SELF_TEST_GUIDE.md` and potentially a public landing page — worse than simply not having an Incidents screenshot yet. **Incidents needs its own dedicated capture pass once this is fixed**, not folded into Phase 7's general sweep. | — | Bug | none | Open |

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

## Batch 3, item 4 closed (2026-08-19) — delete conversation

Investigated before building, per instruction: there is no `ChatSession`
table — a "session" is purely the `session_id` grouping key on
`ChatMessage` rows, confirmed by grep. `Task.originating_session_id`
exists in the schema for exactly this trace-back but is never actually
set by any code path (logged separately as **item 46** — not fixed here).
`ApprovalRequest.session_id` *is* populated for chat-originated approvals,
but the row is fully self-contained (`action_name`/`action_args`/`reason`
all live on it) and nothing joins it back to `chat_messages` at read time,
so a *resolved* approval survives its conversation being deleted with no
functional loss — only a *pending* one is refused.

New `DELETE /api/v1/chat/sessions/{session_id}` (`api/v1/chat.py`): hard-
deletes the `ChatMessage` rows for that session, scoped to tenant+user
(matching `list_sessions`' own scoping). Returns 409 with a real message —
*"This conversation has an approval waiting on your decision. Resolve it
on the Approvals screen before deleting."* — if a `PENDING`
`ApprovalRequest` still traces to that session; a bare refusal with no way
forward would repeat finding 12's dead-end problem, so `Toast` gained an
optional inline action button (`push(message, variant, { label, onClick
})`), used here to link straight to `/approvals`. Delete control is a
hover-revealed **✕** on each row in the AXIOM chat page's session list
(`SessionList.tsx`), the exact location asked for.

Live-verified end to end: created two real conversations via the chat UI,
attached a real `PENDING` `ApprovalRequest` fixture row to one (inserted
directly via SQL, same fixture pattern used for batch 2's CI/CD date
check, deleted after); confirmed the plain conversation deleted instantly
with the session list updating with no manual reload; confirmed the
approval-blocked one produced the exact 409 message with a working **Go
to Approvals** button that navigated to `/approvals`; confirmed that
*after* resolving the fixture approval (`REJECTED`, not deleted), the same
conversation then deleted cleanly — proving the block is genuinely
pending-only, not a blanket "ever had an approval" refusal. `npx tsc
--noEmit` and `npm run build` both clean.

## Batch 3, items 22/23/25 closed (2026-08-19) — settings customization

- **Item 22**: Workspace tab's Timezone field is now a real `<select>` of
  IANA zone names (`frontend/src/lib/timezone.ts`, new), not free text.
  Defaults to the browser's own detected zone (`Intl.DateTimeFormat().
  resolvedOptions().timeZone`) the first time, satisfying "correct
  according to the machine's timezone" out of the box, while staying
  editable per-workspace after that. The real gap this closes: the field
  previously saved to the DB but was never actually *read* by anything —
  `dates.ts`'s `formatApiDate`/`formatApiDateOnly` (built for items 2/3)
  always rendered in the browser's own local zone, full stop, regardless
  of what was saved here. Both now read the configured zone via
  `getStoredTimezone()`, applied through `toLocaleString(undefined,
  {timeZone})`. Live-verified with a real fixture: set the workspace to
  `America/New_York` (deliberately far from this machine's real zone,
  confirmed via `Intl.DateTimeFormat().resolvedOptions().timeZone` →
  `Asia/Calcutta`, so a match can't be coincidental), compared a real
  pipeline run's raw DB timestamp (`2026-08-16 09:45:00`, naive/UTC)
  against the Pipelines page's rendered value (`8/16/2026, 5:44:59 AM`) —
  exactly the expected UTC-4 (EDT) offset. `(app)/layout.tsx` reconciles
  the browser's cached value against the server's on every shell mount,
  same pattern as the existing theme reconciliation.
- **Item 23**: new **Profile** tab in Settings surfaces the real
  `OnboardingProfile` row (role, industry, company size, use cases, data
  stack, completion date) read-only via the existing, previously-unused
  `GET /api/v1/onboarding/` endpoint — no backend changes needed, it
  already returned everything needed. Not editable from here yet (not
  asked for).
- **Item 25**: two of the finding's three asks were built; the third was
  investigated and deliberately deferred, not guessed at:
  - **Slack webhook "double verification"**: new `POST /api/v1/settings/
    test-slack-webhook` sends a real test message to the URL server-side
    (host restricted to `hooks.slack.com` — posting to an arbitrary
    caller-supplied URL from the backend is a textbook SSRF vector, closed
    off since there's no legitimate reason this field needs to reach
    anywhere else). The Notifications tab's **Save** button stays disabled
    until a *changed* Slack URL has passed a real test — editing the field
    after a successful test re-locks Save, since it's re-verifying that
    specific value, not a one-time unlock. **A real bug was found and
    fixed live during this verification**: the endpoint originally raised
    an `HTTPException` for a non-Slack-domain URL, which the frontend's
    generic `request()` helper throws as an `ApiError` on any non-2xx —
    the Test button's error handler only had a path for the `{ok:false,
    error}` 200-status shape every other failure uses, so a bad-domain URL
    showed the same generic "couldn't reach the server" message as a
    genuine dead connection, hiding the real reason. Fixed by making the
    domain check return the same `{ok:false, error}` shape as every other
    failure path. Live-verified all three states: a non-Slack URL (clean,
    specific rejection), a well-formed-but-fake Slack URL (`/services/
    FAKE/FAKE/FAKE` — real POST to Slack, Slack's own `404 no_team`
    response correctly surfaced), and clearing the field back to empty
    (Save re-enabled, no pending unverified change).
  - **"Invalid email task... when the email not verified"**: new
    **Profile** tab card shows an "Email not verified" badge + a
    send-code/verify-code flow when `User.email_verified` is false —
    reuses the *existing*, already-tested email-code login endpoints
    (`POST /auth/email-code/request` + `/verify`) as the ownership proof,
    rather than building new verification infrastructure; re-proving you
    can receive mail at your own current address is functionally the same
    check as logging in via a code. `GET /auth/me` was extended to return
    `email_verified` (previously only `theme`). **A second real bug was
    found live**: `sendCode()` didn't check the request endpoint's
    `status` field, so a rate-limited request (real, pre-existing Redis
    logic — 5/email/hour, 20/IP/hour) returned 200 with `{"status":
    "rate_limited"}` and was shown as a false "code sent" success, leaving
    the user staring at a code box that could never succeed with no
    indication why. Fixed to check `status` and show a real "wait and try
    again" message instead. Live-verified the full flow end-to-end
    against a real DB fixture (a known code's hash inserted directly, to
    avoid needing real inbox access) — code accepted, banner disappeared,
    "Email verified." toast, `email_verified` flipped true via a direct
    `GET /auth/me` check; then reverted the demo account back to
    unverified afterward so the walkthrough account's real state isn't
    artificially changed by this verification pass.
  - **NOT built**: a flow to change your account email to a genuinely
    *new* address. Investigated: no such endpoint exists today at all
    (`PATCH /auth/me` only ever supported `theme`). Real design questions
    with no obvious single right answer — does the JWT need reissuing
    mid-session, is uniqueness checked across every tenant or just the
    caller's own, does the *old* address get notified as a security
    signal — make this a genuinely separate, larger, more security-
    sensitive piece than "verify the email you already have," which is
    all this pass built. Sized but not started; needs a design decision
    before building.
  - Two new items surfaced purely from this verification pass, both
    pre-existing and unrelated to any of the above changes: item 47 (a
    real test-suite fragility — the email-code rate limiter's Redis state
    is shared across an entire pytest session with no per-file reset,
    so a broad enough `-k` selection can spuriously fail two
    `test_email_code_auth.py` tests that pass cleanly in isolation).

## Batch 3, item 13 closed (2026-08-19) — re-run buttons on the Tasks list

Per the user's own clarification before building: re-run buttons live on
the Tasks list, per row, re-running a completed or failed task with the
same goal to generate a fresh plan (not resuming the old one). Cost
confirmed before building, as asked: `generate_plan()` is a real LLM call,
normally exactly 1, up to 2 only if the model's first response is
malformed JSON and needs the existing one-shot corrective retry already
built into `task_planner.py` — identical cost profile to starting any new
task via "+ Start a Task", since re-run calls the exact same
`POST /tasks/` endpoint with the original task's `goal`/`task_shape`.

Button only renders for `completed` / `completed_with_unconfirmed_steps`
/ `failed` — any in-progress or paused status shows nothing. Per the
user's explicit requirement that this not be "one click away from
burning quota without the user knowing": clicking **Re-run** arms the
button into **Confirm — 1 AI call** for 4 seconds (auto-reverts,
nothing spent, if left alone); only the second click actually fires.
No other costly/destructive action in this app uses a confirm step —
this is the only one that spends real AI credits from a list-row click,
which is why it gets one and they don't.

Live-verified against a real completed task, spending one real Gemini
call (12 real calls already logged today before this, well under any
daily concern): confirmed the button is absent on Draft Plan/Paused
rows and present on Completed rows; confirmed a single click arms
without firing (URL/list unchanged); confirmed the arm reverts on its
own after the timeout with nothing spent; confirmed the second click
generates a real plan and navigates straight to the new task's detail
page, landing in Draft Plan exactly like any other new task.

## Batch 3 closed (2026-08-19) — features and backend

Items 4, 22, 23, 25 (partial), 13, and the sized-in tail item 46 — see
each item's own closure note above for full detail. Summary:

- **Item 4** (delete conversation): hard delete, tenant+user+session
  scoped, refuses only on a genuinely pending approval with a route
  forward to Approvals, not a bare refusal.
- **Item 22** (timezone dropdown): real IANA-zone `<select>`, defaults to
  the browser's detected zone, and — the actual gap — now genuinely
  drives every rendered timestamp instead of sitting unread in the DB.
- **Item 23** (onboarding answers in Settings): new read-only Profile
  tab, no backend changes needed.
- **Item 25** (double verification): Slack webhook changes gated behind
  a real test send; an "email not verified" notice with a self-verify
  flow reusing existing login infrastructure. Changing to a genuinely new
  email was investigated and deliberately deferred — real, unresolved
  design questions (JWT reissue, cross-tenant uniqueness, notifying the
  old address), not guessed at.
- **Item 13** (re-run buttons): per-row on the Tasks list for
  completed/failed tasks, cost-confirmed before building, gated behind an
  explicit two-click confirm so it's never a single accidental click away
  from spending AI credits.
- **Item 46** (dead `originating_session_id` column): wired up end to
  end rather than left for later — confirmed live that a task started
  from within a chat session now genuinely records that session's real
  id, and a task started from the bare Tasks list correctly records
  `NULL`.

Three new findings surfaced purely from this batch's own verification
work, all logged and left unfixed per instruction: item 45 (the API's
three timestamp shapes are a real API-contract inconsistency for any
direct API consumer), item 46 itself started as a find before becoming
this batch's own tail fix, and item 47 (a real, pre-existing pytest
fragility — the email-code rate limiter's Redis state has no per-file
reset, so a broad `-k` selection can spuriously fail two otherwise-
passing tests). Two real bugs were found and fixed live during this
batch's own verification, inside the same commits as the features that
surfaced them (not logged as separate findings, since they were bugs in
code being actively written this session, not pre-existing product
bugs): the Slack test endpoint's error shape mismatch, and the email
verification flow's unhandled rate-limited response.

## Item 1 closed (2026-08-19) — remember-last-workspace + real sidebar switcher

Fix is remember, not delete: the choose-workspace picker still exists and
still appears the first time an email resolves to more than one active
tenant, but a successful resolution — however it happened, ambiguous
auto-resolve, an explicit login pick, or an in-app switch — is now
remembered server-side (new `user_workspace_preferences` table, keyed by
email since the same email has a separate `User` row per tenant) and
checked first on every subsequent login, before the picker would ever
show. Written from one choke point (`issue_token_and_remember()`,
wrapping the pre-existing `issue_token_for_user`) covering all 6 real
login/signup/invite-accept/switch call sites, confirmed by grep. A stale
remembered tenant (removed, deactivated) is never trusted blindly — it's
checked against the caller's *current* active candidates on every login,
and falls straight through to the pre-existing single-match/choose-picker
behavior if it's no longer valid.

The sidebar's dead "Production" row (`Sidebar.tsx`) is now a real
switcher: shows the actual current workspace name via the existing
settings fetch, and opens a **Switch workspace** modal (the same
`WorkspacePicker` component login's own choose-workspace step uses,
extended with optional title/subtitle/current-tenant-marking props)
listing every workspace the email has an active account in. New
`POST /api/v1/auth/switch-workspace` re-issues a fresh token — required
since `tenant_id` is baked into the JWT, there is no way to switch
without one — gated on a real DB lookup for an active `User` row
matching the *authenticated* email (from `get_current_user`'s already
freshly-checked identity, never from the request body) and the requested
tenant; failing that lookup 403s. Rate-limited the same real Redis
mechanism email-code login uses (30/email/hour, 60/IP/hour — more
generous than login's OTP limits since this isn't a guessing/brute-force
target, the caller must already hold a valid session and a real active
membership). Writes two `AuditLog` entries per switch, one per tenant
side (`workspace.switched_away` / `workspace.switched_into`), so each
tenant's own audit trail independently shows the event from its own
perspective.

Live-verified against real, disposable fixture tenants (created via the
real `/register` endpoint, cleaned up after — never the reviewer's own
real multi-tenant account): the picker still appears with no remembered
preference; picking a workspace and logging out/back in skips it on the
next login; the sidebar shows the real name and opens a working switcher
listing both workspaces with the current one marked; switching produces
a real new token, a real full-page reload, and lands in the new
workspace with its real name displayed; a stale (deactivated)
remembered tenant falls through cleanly to the one remaining active
membership with no error; an out-of-scope target tenant 403s; both
`AuditLog` entries land with the correct tenant/action/payload; the rate
limit fires a real 429 with a clear message once exceeded. Full backend
suite (398 tests) passed clean both before and after the three review
additions (server-side check confirmation, audit logging, rate
limiting). `npx tsc --noEmit` and `npm run build` both clean.

## Batch 4 (2026-08-19) — propose-only, scope-only, deferred, and one real fix

Item 20 (JWT refresh) and item 28 (chat upload → task) were proposed, not
built, per instruction — full proposals live in this session's own
conversation record, not reproduced here. Item 27 (CI/CD webhook) is
re-marked `Blocked (deployment)` conceptually (kept `Open` in the table
above, since this file has no separate blocked state) — needs a publicly
reachable URL GitHub can reach, which local dev can't provide. Items
17/26 remain `Open`/`Untested`, pending the user creating a second
account via the invite flow.

**Item 47 fixed.** Root cause confirmed precisely: `otp:ip:{ip}` (the
email-code rate limiter's per-IP counter) is shared across every test in
a pytest session with no reset between them, since all requests share
one source "IP" through the ASGI test transport. Added an autouse,
function-scoped fixture in `tests/conftest.py`
(`_reset_email_code_rate_limits`) that clears every `otp:*` Redis key
before each test — the suite no longer depends on what ran before it or
how broad a `-k` selection pulls in.

**Verified the fix actually neutralizes the failure mode, not just that
tests pass by luck**: deliberately set `otp:ip:127.0.0.1` and
`otp:ip:172.18.0.1` to `999` (10x over the real 20/hour cap) via
`redis-cli` immediately before each run, with zero manual cleanup
afterward relying on the new fixture alone —
`pytest tests/test_email_code_auth.py` (11/11) and
`pytest tests/ -k "auth or settings"` (40/40) both passed clean despite
the poisoned starting state that previously caused exactly this failure.
**Full backend suite re-run in full** (not just the affected file/
selection) to confirm the new autouse fixture introduces no regressions
anywhere else: **398 passed, 1 deselected, zero failures.**

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
