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

---

