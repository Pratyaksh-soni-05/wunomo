# Working Agreement: Asynchronous Collaboration on Wunomo

**For:** Pratyaksh and his Claude Code sessions
**From:** Daksh
**Lives at:** `docs/context/WORKING_AGREEMENT.md` (read automatically via `CLAUDE.md`)

---

## 0. Why this exists

Daksh can't answer within the hour, and a question that takes five minutes to ask has been costing hours. This document removes the waiting.

**The one rule that makes it work: Daksh merges everything, so you never need permission to *build*. You only need review to *merge*.** Anything you would have asked in chat goes into the PR description instead, with your recommended answer. Daksh answers when he reviews, and the work continues in the meantime.

You and your Claude should be able to work for several days without messaging Daksh at all.

---

## 1. Session start routine (every session, before writing code)

```
git fetch origin --prune
git status                                  # clean tree before anything else
git branch -r --merged origin/master        # which of your branches already landed
git log --oneline HEAD..origin/master       # what landed on master since you branched
```

- If one of your PRs shows as merged: you do not need an acknowledgement message. Daksh also leaves a PR comment, but this check is the source of truth. Delete the merged branch, then start the next branch from fresh `master`.
- If `master` moved under a branch you are still working on: `git merge origin/master` into that branch (merge, don't rebase, and never force-push), then run the guard tests.
- Check the last `full-suite.yml` run on `master` in GitHub Actions. If `master` is red, see section 10.
- Read `docs/context/STAGE_OWNERSHIP.md` for the stage you are on.

Before switching branches, always run `git status` and commit or stash first. Uncommitted work travels across branches and is easy to commit to the wrong one.

---

## 2. Three lanes: classify every change

Put the lane at the top of the PR. It tells Daksh what to review first.

| Lane | What it is | Examples | PR state |
|---|---|---|---|
| **Green** | UI, styling, copy, docs, tests, internal refactors with no behavior change | rail/nav, Command Center layout, message cards | Ready for review |
| **Yellow** | Backend behavior in your area, no security control involved | supervisor logic, channel features, scheduled tasks, new endpoints behind existing auth | Ready for review |
| **Red** | Anything that touches a security control or an irreversible effect | a file on the CODEOWNERS list; migrations; auth, sessions, MFA, SSO; approvals and the approve-then-execute path; PII/redaction; rate limits; anything that moves money, deletes data, or sends external messages; new tables with `tenant_id`; secrets | **Draft PR** until Daksh has read the design note |

**Red lane does not mean stop.** Build it, put the design note in the PR, mark it Draft, and move to other work. The only thing red changes is that Daksh reads the design before the code.

---

## 3. What you decide yourself

Decide, record, and continue, without asking. Record each decision in the PR description under "Decisions I made":

- Naming, file layout, component structure, copy
- Which of two reasonable implementations to use (record the alternative you rejected and why)
- Whether something is its own PR (if it is unrelated to the branch's purpose: yes)
- Fixing a bug you find in your own area, including bugs found while working on something else
- Adding tests, adding guard tests, improving docs and `GOTCHAS.md` entries
- Test-seeding conventions, tooling, scripts

**Rule of thumb: if it is reversible by reverting one PR, it is yours to decide.**

### Answers to questions you have already asked (so you don't need to ask again)

| You asked | Answer |
|---|---|
| "Want me to take this, or open a PR for it?" | Yes, always take it, always open a PR. |
| "Should this be a separate PR?" | Yes, if it is unrelated to the current branch's purpose. |
| "Is this close to a security-core file?" | Red lane: build it, Draft PR, design note. Do not edit the file; add a helper beside it if you need new behavior. |
| "Should I commit `CONTRIBUTING.md` or a script?" | Docs and tooling that don't change app behavior: yes, in a PR. |
| "I found X across the codebase, want a wider look?" | Write it into `GOTCHAS.md` on your branch, mention it in the PR, keep going. |
| "Your hypothesis was wrong" | Say so in the PR with the trace. That is exactly right. |

---

## 4. Stop-and-ask list (short, on purpose)

Only these. For each, write the question in the PR and **continue on other work while it waits**:

1. **Secrets and external accounts:** creating, rotating or sharing keys, third-party accounts, anything that costs money
2. **Destructive operations on data:** truncating, deleting, bulk updates on shared databases
3. **Pushing to `master`, force-pushing, or rewriting history:** never, under any circumstance
4. **Changing shared infrastructure defaults:** `docker-compose.yml`, CI workflows, Postgres settings
5. **Weakening, skipping or deleting an existing test** to make something pass. If an old test is wrong, say why in the PR; don't edit it silently.

**If Daksh hasn't answered a yellow-lane question within 24 hours, the default you recorded stands.** Flag it in the next PR so it gets reviewed.

---

## 4b. What counts as urgent (message Daksh immediately)

1. A secret was committed or exposed
2. One tenant's data is visible to another tenant
3. `master` or CI is broken in a way that blocks everyone
4. Something could cause irreversible data loss or move money

For these, send Daksh one line with the PR or branch link, and keep working on other things while waiting. Nothing else is urgent.

---

## 5. Migrations and `.env` (self-serve, no announcement needed)

Before generating a migration:

```
git fetch origin
git ls-tree -r --name-only origin/master -- dataops-agent/backend/migrations/versions | tail
```

- Check open PR branches for migration files too.
- If two heads exist after you merge, run `alembic merge heads`. Never edit another migration's `down_revision`.
- Every new table with a `tenant_id` ships in the **same migration** with `ENABLE` + `FORCE ROW LEVEL SECURITY`, a `tenant_isolation` policy, a `GRANT` to `dataops_app`, and an entry in conftest's teardown `DELETION_PLAN`. The RLS guard test fails CI otherwise.
- Any new `.env` key goes in `.env.example` in the same commit, with a placeholder value only.

---

## 6. Branches and stacking

- Branch from fresh `master`: `feature/<stage-or-area>-<short-name>`.
- Independent work gets its own branch from `master`. **Maximum three open PRs stacked on each other. Daksh reviews in batches roughly every 3-4 days, so you will often have several PRs open at once. If a fourth would depend on an unmerged PR, start an independent stream from master in a different area instead of stacking deeper.**
- When the base PR merges, retarget the next PR to `master` and merge `master` into it.
- Push at least every 2-3 days, even if unfinished (open a Draft PR). Never leave work only on your laptop.
- Address review comments with new commits on the same branch. Do not force-push.

---

## 7. Definition of done (this is what makes review fast)

Every PR must contain, in the description:

1. **Prefix the PR title with `[green]`, `[yellow]` or `[red]`** (the lane), so the PR list can be scanned at a glance.
2. **Lane** and the reason for it
3. **Decisions I made**: decision, alternative, why, whether it is easy to reverse
4. **Questions for Daksh**: each with your recommended answer and "will proceed with this default if no answer in 24h"
5. **Test evidence**: `scripts/fast_pretest.sh` result, both guard tests, and a **`full-suite.yml` run on your branch** (trigger it with `workflow_dispatch`) with the link
6. **How to see it working**: two or three steps Daksh can follow in the browser or with a curl command
7. **Security checklist** (the six rules, ticked or marked not applicable)
8. **CODEOWNERS files touched** (list them, or "none")
9. **Out of scope / follow-ups**

For bug fixes: show the test **fails without the fix and passes with it**. For anything with a live effect: verify it live, not only in mocks. Claims in the description should be things Daksh can check, not things he has to trust.

---

## 8. When you find a bug or a security issue

Don't wait for an answer. Do all of these:

1. Reproduce it first. Measure before you assume.
2. Fix it if it is in your lane; if it is red-lane, write the fix as a Draft PR.
3. Add an entry to `docs/context/GOTCHAS.md`. **Append only.** Never rewrite old entries; mark them `[CORRECTED]` or `[RESOLVED]` instead.
4. Put it at the top of the PR description under "Findings", especially anything that is more serious than the thing you were fixing. (The double-execution you found in the approval path is the model example.)

---

## 9. Review, merge and acknowledgement

**What Daksh does:** reviews in batches roughly every 3-4 days, red lane first, using a fixed routine (diff, CODEOWNERS check, standing patterns, CI, the full-suite run on your branch). He merges with a regular merge commit. Until your PR is merged, keep building; never wait for a merge. Treat every non-urgent question as already answered by the default you recorded.

**What you see:** after merging, Daksh (or his Claude) posts a **comment on the PR** with the merge commit SHA, `master`'s full-suite result, and what to do next. You will also see it in the section 1 check, so the comment is a convenience, not something you have to wait for.

**What you do after a merge:**

```
git fetch origin --prune
git checkout master && git merge --ff-only origin/master
git branch -d <merged-branch>
# any branch you are still working on:
git checkout <branch> && git merge origin/master
scripts/fast_pretest.sh
```

**Review comments:** if Daksh requests changes, they come as PR review comments. Fix them in new commits. Don't reopen the discussion in chat unless the comment is unclear.

---

## 10. If `master` is red

Check which tests fail on `master` before reading your own result. If the same tests fail on `master`, they are not yours; say so in the PR and do not try to fix them unless the failure is in your area. Daksh fixes `master` first. Avoid merging into or stacking on a red base.

---

## 11. The standing rules (unchanged, one line each)

1. Every new `tenant_id` table has RLS in the same migration (guard test enforces it).
2. Every Celery or scheduled task establishes tenant context (guard test enforces it). Never use a bare `AsyncSessionLocal()` for tenant-scoped reads.
3. Never return an error as HTTP 200. Raise `HTTPException`.
4. Never create a second hand-maintained list of tools, models or capabilities. Derive it from the single source.
5. Every session is minted through `issue_token_and_remember()`.
6. Migrations and `.env` keys follow section 5.

Also: any code matching LLM output against characters (UUIDs, SSNs, phone numbers) must normalize with `normalize_for_matching()` first. Models emit look-alike Unicode hyphens.

---

## 12. Paste this at the start of Claude Code sessions

```
Read docs/context/WORKING_AGREEMENT.md, STAGE_OWNERSHIP.md and
GOTCHAS.md first. Work asynchronously: never block on a question.
For anything you would normally ask the repo owner, decide, record the
decision and your recommended default in the PR description, and
continue; PRs are the checkpoint, not chat. Classify every change as
green, yellow or red (section 2) and open red-lane PRs as Draft with a
design note. Stop and ask only for the five items in section 4, and
keep working on other things while waiting. Start every session with
the section 1 routine. Never push to master. Every PR needs the
section 7 contents, including a full-suite.yml run on your branch.
Prefix PR titles with [green]/[yellow]/[red]. Up to three stacked PRs
are allowed.
```
