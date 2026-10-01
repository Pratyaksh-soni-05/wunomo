## Summary
<!-- What this PR does and why, in 2-4 sentences. -->

## Lane
<!-- green / yellow / red, and why. Red lane = Draft PR. See docs/context/WORKING_AGREEMENT.md section 2. -->

## Findings
<!-- Anything you found that is more serious than what you set out to fix, or a bug in code you did not change. "None" if none. -->

## Decisions I made without asking
<!-- Decision | alternative I rejected | why | easy to reverse? (one row each) -->

## Questions for Daksh
<!-- Each with a recommended answer. "If no answer within 24h, I proceed with the default." -->

## How to see it working
<!-- 2-3 steps in the browser or a curl command. -->

## Test evidence
- [ ] `scripts/fast_pretest.sh`: result:
- [ ] Both guard tests pass (`test_rls_coverage_guard.py`, `test_celery_tenant_context_guard.py`)
- [ ] `full-suite.yml` run on THIS branch (via workflow_dispatch): link / result:
- [ ] Bug fixes: the test fails without the fix and passes with it

## Security checklist (tick or write N/A)
- [ ] New `tenant_id` tables: RLS enable + force + policy + GRANT + conftest teardown, same migration
- [ ] New Celery or scheduled tasks: tenant context established
- [ ] No error returned as HTTP 200
- [ ] No new hand-maintained list of tools, models or capabilities
- [ ] No session minted outside `issue_token_and_remember()`
- [ ] New `.env` keys added to `.env.example`; migration heads merged, not edited
- [ ] Text matching against LLM output uses `normalize_for_matching()`

## CODEOWNERS files touched
<!-- List them, or "none". If any: this must be a Draft PR with a design note. -->

## Out of scope / follow-ups
