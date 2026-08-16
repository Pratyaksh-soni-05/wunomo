# Workflow Rules

> Archived verbatim from CLAUDE.md on 2026-08-12, during the account-migration
> checkpoint session. This was section 4 of the old CLAUDE.md. See
> `docs/context/SESSION_LOG.md`'s 2026-08-12 entry for why this split happened.

## 4. Workflow Rules

These govern how any Claude Code session (including this one) operates on this repo:

1. **Read this file in full at the start of every session before taking any action.**
2. **Work one issue or feature per session.** Verify each fix against the real running system (start the stack, hit the actual endpoint/flow, don't just eyeball the diff) before moving to the next one. Don't batch multiple unverified changes together.
3. **If verifying a fix surfaces a new or hidden related bug, resolve it in the same session** rather than stopping at the original scope — but still commit it separately (see rule 5).
4. **For any non-trivial feature or architectural change, propose the approach and tradeoffs first and wait for approval before writing code.** This includes anything touching tenant isolation, auth, the approval workflow, or the Celery scheduling mismatch — these are exactly the areas where a quick fix can silently reintroduce one of the gotchas above.
5. **Write or update a regression test alongside every bug fix, in the same commit.** Given current test coverage (auth + smoke only), most fixes in `agent/`, `modules/`, or `services/` will be the first test for that code path — that's expected, not a sign you're doing extra work.
6. **Commit after every individually verified fix**, with a message describing the issue and how it was verified. Don't batch multiple fixes into one commit.
7. **Update this file's Status Table and Known Gotchas section as part of the same commit** whenever something is fixed, added, or newly discovered. Move superseded information into the Archive below rather than deleting it.
8. Given there are no commits yet in this repo, the first commit is an unusually large diff — that's expected, but subsequent commits should follow the one-fix-per-commit rule above.
9. **When a fix supersedes an existing Known-broken row, mark that row `[RESOLVED: <how/when>]` in the *same* commit as the fix — never just add a new row and leave the old one riding.** This has already failed silently three times in this project (the `login()`/`register()` disambiguation rows, and `request_approval`, all fixed sessions before anyone marked them resolved) — each time because the fix's own commit only touched the Status Table, not the matching Known-broken row, and nothing ever prompted a later pass to reconcile them. A stale "known-broken" row is worse than no row at all: it actively tells a future session (or an outside reader, like the Phase 19 user manual) that something is still wrong when it isn't. Before closing out any commit that fixes a documented bug, grep the Known-broken table for that bug's description and update it in the same commit — don't defer it to a later cleanup pass.
10. **A task-shape (or task-execution) change is not verified until a real task reaches `COMPLETED`, end to end, through the actual UI or a real API call — not a mock, not "the approval card rendered correctly," not "it failed in the expected/documented way."** Established 2026-08, after finding that Item 6's stages 1–7 had verified every individual piece of the Tasks machinery (plan generation, edit, approve, the approval gate, resume, termination caps) without a single human-run, non-trivial task shape (one that references a named entity) ever actually reaching `COMPLETED` — the machinery was real and each piece worked as designed, but the thing it was all built to produce (a completed task) had never once actually happened outside of a maximally vague goal that avoided the failure mode by luck. See `docs/context/SESSION_LOG.md`'s 2026-08 entries for the full diagnosis and the fix this rule was written alongside. A regression test proving the *mechanism* behaves correctly under mocks is still required (rule 5) — it's necessary, but this rule exists because it turned out not to be sufficient on its own for this specific class of feature (multi-step, LLM-planned execution), and nothing short of a real end-to-end run would have caught the gap.

---

