"""Item 6 (long-running AXIOM tasks) -- stage 3 (execution core) + stage 4
(verification, Q2). See docs/PRODUCT_AUDIT.md section 1.9 for the design.

execute_next_step(task_id) advances a QUEUED/RUNNING task by exactly one
unit of work per call -- either resolving a step to a terminal state
(SUCCEEDED or FAILED, including whatever retries/adaptation its failure
tier calls for), or re-polling a step that's still VERIFYING. Directly
callable (tests, live verification, manual driving via
POST /tasks/{id}/advance); no automatic Celery scheduling is wired yet
(deliberately out of scope -- see CLAUDE.md).

Failure tiers (Q1), in the order a step's attempts are classified:
  - PERMISSION: the fresh per-step role/is_active re-check (amendment 3)
    fails. Never retried -- retrying a deterministic denial wastes
    nothing but time, and the caller needs to know now, not after a
    pointless wait. Counts as exactly 1 attempt.
  - TRANSIENT: the tool call raised a real exception. One bounded retry
    with a short backoff, same arguments, no LLM involved.
  - DOMAIN: the tool call returned cleanly but its own result dict
    contains an "error" key (this codebase's established convention for
    a tool signaling a real, structured failure -- "Pipeline not found",
    etc.). Gets exactly one LLM-adapt attempt: the real error is shown to
    the LLM, which may propose different arguments (or leave them
    unchanged if it can't improve on them).
A step gets at most 3 total attempts (1 initial + up to 2 recovery
attempts: one transient-retry OR one domain-adapt, whichever applies,
and a final attempt if the first recovery attempt also failed). At most
one LLM-adapt call is ever made per step, regardless of how many
attempts it takes. Once budget is exhausted, the step is marked FAILED
with the real underlying error message and the task pauses
(PAUSED_FAILED_STEP) -- never abandoned, never silently continued.

Verification (Q2): if a dispatching step's tool call succeeds
*structurally* but its result looks like an async dispatch (a real,
recognized shape -- currently only run_pipeline's
{"status": RunStatus.PENDING, "run_id": ...}), the dispatching step is
marked SUCCEEDED (it genuinely did dispatch) and a NEW, separate
TaskStep is appended with source=SYSTEM_INSERTED, depending on the
dispatching step's index -- never a status recycled onto the same step,
so a plan review can always tell what AXIOM planned from what the system
added (amendment 3's sibling requirement for stage 4). That new step is
polled on each subsequent call, purely against real elapsed wall-clock
time (VERIFY_TIMEOUT_SECONDS, measured from the step's own started_at,
which shares Task.started_at's clock -- no separate timer for stage 6's
eventual wall-clock cap to forget about), never against step_budget_used
or the 3-attempt tier budget -- those govern retrying a tool call, not
watching one that already succeeded at dispatch time.

Completion is honest by construction: the "no pending steps left, mark
COMPLETED" branch is only reachable when zero steps are still
VERIFYING. If the only thing left unresolved is a timed-out verify step,
the task goes to COMPLETED_WITH_UNCONFIRMED_STEPS instead -- never a
clean COMPLETED that silently ignores it.
"""
import asyncio
import json
import re
import uuid
from collections import Counter
from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, func

from database import AsyncSessionLocal
from agent.personality import get_risk_level
from modules.governance.policy_engine import PolicyEngine
from modules.orchestration.task_planner import tool_by_name, tool_schema_for_prompt
from models.all_models import (
    AgentInstance, AgentInstanceStatus, ApprovalRequest, ApprovalStatus, Incident, IncidentSeverity,
    IncidentStatus, RUNNABLE_TASK_STATUSES, RunStatus, Task, TaskStatus, TaskStep, TaskStepSource,
    TaskStepStatus, User,
)
from services.agent_scope import agent_scope_denial_reason
from services.llm_service import invoke_llm
from services.quota_service import get_agent_quota_status, get_quota_status
from services.rbac import TOOL_CAPABILITIES, has_permission

MAX_ATTEMPTS_PER_STEP = 3  # 1 initial + up to 2 recovery attempts
TRANSIENT_RETRY_BACKOFF_SECONDS = 2
VERIFY_TIMEOUT_SECONDS = 300  # real wall-clock budget for a dispatched step to reach a terminal state
APPROVAL_PAUSE_TIMEOUT_HOURS = 48  # Q5 amendment: a paused-for-approval task doesn't wait forever
MAX_TASK_WALL_CLOCK_HOURS = 4  # Q4: real elapsed time since Task.started_at, covers time spent verifying too
LOOP_DETECTION_THRESHOLD = 3  # same (tool, args) signature attempted this many times = no progress, not persistence

TIER_PERMISSION = "permission"
TIER_TRANSIENT = "transient"
TIER_DOMAIN = "domain"

# Tools this codebase can genuinely verify the async result of.
# run_pipeline (DAGManager.trigger_run()) is the only real async-dispatching
# tool in the whole registry today -- confirmed by reading every tool in
# agent/tools/*.py, not assumed. It is deliberately NOT in any
# TASK_SHAPE_ALLOWED_TOOLS entry yet: exposing a real, mutating,
# fire-and-forget tool to the planner with no per-step approval gate
# (that's stage 5) would be a real safety regression against the whole
# reason item 6 was built before item 7. This mechanism is real and
# tested against the real run_pipeline/Celery/PipelineRun infrastructure
# (see CLAUDE.md's live-verification note), just not reachable through
# the locked planner allowlists until stage 5 exists.
_VERIFIABLE_TOOLS = {"run_pipeline"}

log = structlog.get_logger()


async def _caller_still_authorized(db, task: Task, tool_name: str, tool_args: dict) -> tuple[bool, str | None, dict | None]:
    """Fresh, per-step re-read of the task's initiating user's
    is_active/role, the calling agent's own status (Wunomo Projects Phase
    2 frontend, slice 4 -- OFFBOARDED must be enforced, not just
    displayed: a status that only greys out a UI card is a label, not a
    state), AND (Wunomo Projects Phase 1) the calling agent's current
    scope -- never trusts anything cached on Task (there is nothing to
    trust; Task carries no role column by design, see amendment 3).
    Mirrors get_current_user()'s own per-request re-read for REST, applied
    here at the step-execution boundary instead. An agent can be
    re-scoped, offboarded, or a user demoted mid-task; this re-checks all
    three, the same way, at the same call site.

    The scope half only ever has something real to check when tool_args
    already holds a resolved value, not a planner/human-edit placeholder
    -- agent_scope_denial_reason() treats an unresolved/absent value as
    nothing to check yet, not as allowed forever. That's correct here:
    the unconditional backstop that always sees fully-resolved args is
    the separate scope check immediately before _call_tool() in
    execute_next_step()'s attempt loop below -- "this is where the
    guarantee lives" per CLAUDE.md's plan-time-vs-enforcement split, not
    this function. This function's own scope check earns its keep on a
    RESUME (a step whose args were already resolved on an earlier call,
    e.g. while waiting on approval) where the agent's scope may have
    changed since resolution happened.

    Returns (authorized, message, scope_denial) -- scope_denial is the
    full structured dict from agent_scope_denial_reason() (Wunomo
    Projects Phase 2 frontend, slice 9), non-None ONLY when the denial was
    specifically a scope gap, so the caller can trigger the deduped
    "grant access" notification for that cause alone -- not for the other
    three (user deactivated, role changed, agent offboarded), which have
    no comparable single-action fix or "recurs across many tasks" shape."""
    r = await db.execute(select(User.is_active, User.role).where(User.id == task.user_id))
    row = r.first()
    if row is None or not row.is_active:
        return False, "the initiating user's account is no longer active", None

    # task.agent_id is nullable -- older/agent-less tasks predate Wunomo
    # Projects Phase 1's agent wiring and never set it. No agent_id means
    # no agent to offboard-check, not an offboarded one: skip, don't block.
    if task.agent_id is not None:
        r = await db.execute(select(AgentInstance.status).where(AgentInstance.id == task.agent_id))
        agent_status_row = r.first()
        if agent_status_row is None or agent_status_row[0] != AgentInstanceStatus.ACTIVE:
            return False, "the calling agent has been offboarded", None

    capability = TOOL_CAPABILITIES.get(tool_name)
    if capability is None or not has_permission(row.role, capability):
        return False, f"the initiating user's role ('{row.role}') no longer has permission to use '{tool_name}'", None
    scope_denial = await agent_scope_denial_reason(db, task.agent_id, tool_name, tool_args)
    if scope_denial is not None:
        return False, scope_denial["message"], scope_denial
    return True, None, None



# Deterministic argument resolution (Tier 1, 2026-08 — see
# docs/context/SESSION_LOG.md for the full diagnosis). Which target arg
# key maps to which discovery tool's output is explicit and small rather
# than a generic "find any list of dicts" scan, so a name collision across
# unrelated entity types (a source and a pipeline sharing a name) can't
# cross-contaminate a resolution. Extend this dict, not the matching
# logic, when a new discovery tool + entity type is added. Field names
# genuinely differ per tool (confirmed by reading each one, not assumed):
# list_data_sources/list_pipelines wrap in {"sources"/"pipelines": [...]},
# id key "id", name key "name"; list_open_incidents returns a bare list
# (cap_tool_result only wraps empty results), id key "incident_id", name
# key "title" — not "id"/"name" like the other two.
#
# generic_terms (2026-09): words inherent to this entity type that must
# never carry matching signal, regardless of pool size — see
# _score_candidates' own docstring for why pool-relative IDF alone isn't
# enough (it degrades to a no-op at pool size 1, exactly the case
# test_honest_failure_message_when_neither_tier_resolves guards against:
# a description sharing only the word "pipeline" with the one discovered
# pipeline must never count as a real match).
_ARG_RESOLUTION_SOURCES = {
    "source_id": {
        "discovery_tool": "list_data_sources", "list_key": "sources", "id_key": "id", "name_key": "name",
        "generic_terms": frozenset({"source", "sources", "data"}),
    },
    "pipeline_id": {
        "discovery_tool": "list_pipelines", "list_key": "pipelines", "id_key": "id", "name_key": "name",
        "generic_terms": frozenset({"pipeline", "pipelines"}),
    },
    "incident_id": {
        "discovery_tool": "list_open_incidents", "list_key": None, "id_key": "incident_id", "name_key": "title",
        "generic_terms": frozenset({"incident", "incidents", "data", "stale", "overdue"}),
    },
}

# Tuned against two real failures from the 2026-09-02 measurement session,
# not from first principles — see docs/context/GOTCHAS.md for the full
# worked numbers this was tuned against:
#   Case 1 (should resolve): "the sales pipeline" vs {Sales Ingestion
#   Pipeline, HR Sync Pipeline} scored 0.500 vs 0.000 (HR Sync Pipeline's
#   own tokens never appear in the description at all) — an infinite
#   margin, floor cleared by a wide margin too.
#   Case 2 (should refuse): "the stale sales data incident" vs 20 near-
#   identical "Stale data: <X> (Nh overdue)" incidents scored 0.025 tied
#   across all 10 same-source candidates — a 1.0x margin (no margin at
#   all), and 0.025 sits well below the floor independently.
_TIER1_MATCH_FLOOR = 0.1     # case 2's top score (0.025) sits well below this
_TIER1_MATCH_MARGIN = 1.5    # case 1's real margin clears this; case 2's 1.0x doesn't

# General-purpose English function words — deliberately small, tuned
# against the real descriptions seen so far, not an exhaustive list.
_STOPWORDS = frozenset({
    "the", "a", "an", "to", "of", "for", "on", "in", "is", "and", "its",
    "that", "this", "with", "it", "why", "was", "be",
})


def _tokenize(text: str, generic_terms: frozenset = frozenset()) -> set:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and t not in generic_terms}


def _score_candidates(description: str, records: list[dict], generic_terms: frozenset) -> list[tuple]:
    """Tokenized, pool-relative overlap scoring — replaces plain substring
    containment (2026-09; see docs/context/GOTCHAS.md for why: "sales
    pipeline" is not a substring of "Sales Ingestion Pipeline" in either
    direction, so a real, unambiguous match used to refuse and cost an
    extra real LLM call every time).

    Each candidate's score is the sum of its own name-tokens found in the
    description, weighted inversely by how many OTHER candidates in this
    same pool share that token, normalized by the candidate's own token
    count — a word every candidate's name has in common carries near-zero
    discriminating weight; a word only one candidate has carries most of
    the score. Deliberately cheap (pool sizes here are single digits to a
    few dozen) — no LLM call, matching Tier 1's existing design rationale.

    Pool-relative weighting alone isn't sufficient at small pool sizes: a
    pool of one candidate makes every one of its own tokens trivially
    "unique" (df=1) even if the word is a generic type-name like
    "pipeline" that carries zero real signal. generic_terms (per arg_key,
    see _ARG_RESOLUTION_SOURCES) is stripped from both sides before
    scoring specifically to close that gap, rather than relying on IDF to
    catch something IDF structurally cannot catch at pool size 1.

    Returns a list of (id, name, score) sorted by score descending —
    never mutates, never picks a winner itself; the caller applies the
    floor/margin decision."""
    desc_tokens = _tokenize(description, generic_terms)
    name_tokens = {rec["id"]: _tokenize(str(rec["name"]), generic_terms) for rec in records}
    df = Counter()
    for toks in name_tokens.values():
        for t in toks:
            df[t] += 1
    scored = []
    for rec in records:
        toks = name_tokens[rec["id"]]
        if not toks:
            scored.append((rec["id"], rec["name"], 0.0))
            continue
        matched = toks & desc_tokens
        score = sum(1.0 / df[t] for t in matched) / len(toks)
        scored.append((rec["id"], rec["name"], score))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


async def _discovered_records_for_arg(db, task_id: str, arg_key: str) -> list[dict]:
    """Every real {"name": ..., "id": ...} pair a prior SUCCEEDED discovery
    step for this arg_key actually returned, across the whole task so far
    — the one piece of raw evidence both _candidate_ids_for_arg (Tier 1,
    filtered to a single step's own description below) and
    _all_discovered_ids_for_arg (Tier 2's guardrail, unfiltered) are built
    from. Neither tier is ever allowed to treat an id as real unless it
    traces back to a record in this list."""
    spec = _ARG_RESOLUTION_SOURCES.get(arg_key)
    if spec is None:
        return []
    r = await db.execute(
        select(TaskStep).where(
            TaskStep.task_id == task_id,
            TaskStep.tool_name == spec["discovery_tool"],
            TaskStep.status == TaskStepStatus.SUCCEEDED,
        )
    )
    discovery_steps = r.scalars().all()

    records = []
    for ds in discovery_steps:
        raw = ds.raw_result
        recs = raw if spec["list_key"] is None else (raw or {}).get(spec["list_key"])
        if not isinstance(recs, list):
            continue
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            name, rid = rec.get(spec["name_key"]), rec.get(spec["id_key"])
            if name and rid:
                records.append({"name": name, "id": rid})
    return records


async def _candidate_ids_for_arg(db, task_id: str, step: TaskStep, arg_key: str) -> set:
    """The real ids _resolve_step_args (Tier 1) or _unresolved_reference_
    note (Commit 4) would consider a match for arg_key, given this task's
    own earlier discovery steps and this step's own description. Shared
    so both "resolve it" and "explain why it's still wrong" read the
    identical evidence — a message that says "no source matched" must be
    checking the same thing resolution itself checked, not a second,
    possibly-inconsistent notion of a match.

    Every real decision this function makes — matched or refused — is
    logged with the top two candidates' scores (2026-09), so a resolution
    misfire in front of a customer is diagnosable from logs alone, without
    needing to reproduce the exact discovered pool and description that
    produced it. Always returns a set of size 0 or 1, never more — an
    ambiguous pool is reported as a refusal (with both leading scores in
    the log line), not as a multi-candidate set; callers only ever
    branched on "exactly one" vs "not exactly one" anyway."""
    records = await _discovered_records_for_arg(db, task_id, arg_key)
    if not records:
        log.info(
            "tier1_match_refused", task_id=task_id, step_id=step.id, arg_key=arg_key,
            reason="no_candidates_discovered",
        )
        return set()

    generic_terms = _ARG_RESOLUTION_SOURCES[arg_key].get("generic_terms", frozenset())
    scored = _score_candidates(step.description or "", records, generic_terms)
    top_id, top_name, top_score = scored[0]
    second_name, second_score = (scored[1][1], scored[1][2]) if len(scored) > 1 else (None, 0.0)
    margin = (top_score / second_score) if second_score > 0 else float("inf")

    if top_score >= _TIER1_MATCH_FLOOR and margin >= _TIER1_MATCH_MARGIN:
        log.info(
            "tier1_match_resolved", task_id=task_id, step_id=step.id, arg_key=arg_key,
            matched_id=top_id, matched_name=top_name,
            top_score=round(top_score, 4), second_name=second_name, second_score=round(second_score, 4),
        )
        return {top_id}

    reason = "below_floor" if top_score < _TIER1_MATCH_FLOOR else "no_clear_margin"
    log.info(
        "tier1_match_refused", task_id=task_id, step_id=step.id, arg_key=arg_key, reason=reason,
        top_name=top_name, top_score=round(top_score, 4),
        second_name=second_name, second_score=round(second_score, 4),
    )
    return set()


async def _all_discovered_ids_for_arg(db, task_id: str, arg_key: str) -> set:
    """Tier 2's never-guess guardrail evidence: every real id this task has
    discovered for arg_key so far, regardless of whether the current step's
    own description names it — deliberately broader than
    _candidate_ids_for_arg (that description-restricted match is Tier 1's
    job, already tried and already failed by the time Tier 2 runs). Tier 2
    is allowed to succeed where Tier 1 couldn't (e.g. a step whose
    description paraphrases rather than quotes the record it means), but
    only when this pool has exactly one real candidate — with 2+, picking
    one is exactly the unjustified guess-between-plausible-matches Tier 1
    already refuses to make (_resolve_step_args's own rule), just made by
    an LLM instead of a substring match. Found live, 2026-08-17: without
    this, a diagnose_pipeline_failure task targeting a nonexistent
    pipeline had its pipeline_id silently swapped onto a real, unrelated
    pipeline from this same pool, and the step reported success."""
    records = await _discovered_records_for_arg(db, task_id, arg_key)
    return {rec["id"] for rec in records}


async def _reject_ungrounded_adaptation(db, task_id: str, original_args: dict, adapted_args: dict) -> dict:
    """Applied to every Tier 2 (_adapt_step_args) result before it's used
    for the next attempt. For each _id-shaped key Tier 2 changed, the new
    value is kept only if it's a real id this task actually discovered for
    that key AND that discovery pool has exactly one member — see
    _all_discovered_ids_for_arg for why "exactly one," not just "is real."
    A rejected key reverts to whatever it held before this adapt call
    (almost always the same unresolved placeholder Tier 1 already declined
    to touch), so the step fails again on the next attempt with nothing
    new — and, once attempts are exhausted, _unresolved_reference_note
    reports it honestly instead of a silently-wrong "success". Keys Tier 2
    left unchanged, and any key outside _ARG_RESOLUTION_SOURCES entirely
    (nothing here constrains those), pass through untouched."""
    result = dict(adapted_args)
    for arg_key in _ARG_RESOLUTION_SOURCES:
        if arg_key not in adapted_args:
            continue
        proposed = adapted_args[arg_key]
        if proposed == original_args.get(arg_key):
            continue
        pool = await _all_discovered_ids_for_arg(db, task_id, arg_key)
        if proposed not in pool or len(pool) != 1:
            result[arg_key] = original_args.get(arg_key)
    return result


async def _unresolved_reference_note(db, task_id: str, step: TaskStep, tool_args: dict) -> str | None:
    """Commit 4: honest failure messaging. Called only once a step has
    exhausted its attempt budget and is about to fail — checks whether any
    of its _id-shaped arguments still don't match a real record this task
    actually discovered, using the exact same matching _resolve_step_args
    already tried. Deliberately re-checked fresh here rather than threaded
    through from the original resolution attempt: an approval-gated step
    resolves once, at the approval-gate call, and can fail much later on
    a separate resume call — there's no in-memory state connecting those
    two calls, and adding persisted state just to carry this note across
    them would be exactly the kind of new state the idempotency design
    was built to avoid needing. Re-deriving it from the same evidence at
    failure time is cheap (no LLM call) and always consistent with
    whatever resolution actually did or didn't do.

    Returns None if nothing looks reference-shaped (a genuinely different
    kind of failure) — callers should fall back to the raw tool error
    alone in that case, not invent a resolution story that isn't real.

    tool_args is passed explicitly rather than read off step.tool_args —
    the DB row is only ever updated on a step's success, so by the time a
    step has exhausted its attempts, step.tool_args can still hold the
    pre-Tier-2 value while the real last-attempted args (post-adapt) only
    ever existed in execute_next_step()'s local current_args. Checking
    against what was actually last tried, not what's persisted, is what
    makes this note honest."""
    unresolved = []
    for arg_key in _ARG_RESOLUTION_SOURCES:
        if arg_key not in tool_args:
            continue
        candidates = await _candidate_ids_for_arg(db, task_id, step, arg_key)
        if tool_args[arg_key] not in candidates:
            unresolved.append((arg_key, len(candidates)))
    if not unresolved:
        return None
    parts = [
        f"'{key}' ({'no match' if n == 0 else f'{n} ambiguous matches'} for "
        f"this step's description among what this task discovered earlier)"
        for key, n in unresolved
    ]
    return "Could not determine the real value for " + ", ".join(parts) + "."


async def _resolve_step_args(db, task_id: str, step: TaskStep) -> dict:
    """Tier 1 (deterministic): the task planner generates a step's entire
    tool_args upfront, before any earlier step has actually run — it
    structurally cannot know a real ID a prior discovery step (e.g.
    list_data_sources) hasn't fetched yet, so it writes a plausible-looking
    placeholder instead (e.g. "sales_orders_source_id"), which then fails
    every time. This replaces that placeholder with the real ID by
    matching the target entity's name/title against THIS step's own
    human-readable description — no LLM call, and more reliable than one,
    since it reads the actual fetched record rather than guessing from a
    schema + error message. Falls through untouched (Tier 2's
    _adapt_step_args gets a shot on failure) for any arg not covered by
    _ARG_RESOLUTION_SOURCES, or where the match is ambiguous (0 or 2+
    candidates) — never guesses between multiple plausible matches.

    Callers are responsible for never invoking this on a human-edited step
    (source == HUMAN_EDITED) — a human who typed a specific value meant
    that value, deterministic "correction" or not. Also relied on for
    idempotency: both call sites additionally guard so a given step's args
    are resolved at most once, ever (see the risk-tier split in
    execute_next_step) — this function itself doesn't re-check that, its
    callers own that guarantee.
    """
    tool_args = dict(step.tool_args or {})
    resolved = dict(tool_args)

    for arg_key in _ARG_RESOLUTION_SOURCES:
        if arg_key not in tool_args:
            continue
        candidates = await _candidate_ids_for_arg(db, task_id, step, arg_key)
        if len(candidates) == 1:
            resolved[arg_key] = candidates.pop()
        # 0 or 2+ candidates: leave as-is, Tier 2 gets a shot on failure.

    return resolved


_ADAPT_PRIOR_RESULTS_MAX_CHARS = 3000  # keeps the adapt prompt bounded regardless of how much a discovery step returned


async def _adapt_step_args(
    tenant_id: str, user_id: str, description: str, tool_name: str, tool_args: dict,
    error_message: str, prior_results: list[dict] | None = None, task_id: str | None = None,
) -> dict:
    """One LLM call: shows the real failure to the model and asks for
    corrected arguments. Falls back to the original arguments (a no-op
    "adaptation") if the LLM's response isn't a usable JSON object, or if
    the tenant is out of AI-credit quota -- adaptation is a nice-to-have
    recovery step, not something that should itself crash a task.

    Tier 2 fallback (2026-08): only reached when Tier 1's deterministic
    match (_resolve_step_args) was ambiguous or didn't apply -- so this is
    already the harder case, not the common one. prior_results (this
    task's own earlier successful steps, e.g. a list_data_sources call's
    real, fetched records) is given directly, for the same reason Tier 1
    reads raw_result instead of guessing: an LLM correcting a wrong ID
    from the schema and an error message alone is guessing blind, with no
    way to know what the real ID actually is unless shown it.

    task_id is trailing/keyword-only, not inserted alongside the original
    positional params, deliberately: a test fixture that monkeypatches this
    whole function with its own fake (several do, in tests/test_task_executor*.py)
    and doesn't yet accept task_id gets a clean, obvious TypeError for a
    missing kwarg instead of every downstream positional argument silently
    shifting by one slot."""
    quota = await get_quota_status(tenant_id, "ai_credits")
    if quota["status"] == "exceeded":
        return tool_args

    schema = tool_schema_for_prompt(tool_name)
    context = ""
    if prior_results:
        text = json.dumps(prior_results, default=str)
        if len(text) > _ADAPT_PRIOR_RESULTS_MAX_CHARS:
            text = text[:_ADAPT_PRIOR_RESULTS_MAX_CHARS] + "... (truncated)"
        context = (
            f"\nReal results from earlier steps in this same task (use these to find "
            f"the correct real value -- do not guess a new placeholder):\n{text}\n"
        )
    prompt = (
        f'A task step just failed. Step: "{description}"\n'
        f"Tool: {tool_name}\n"
        f"Arguments used: {json.dumps(tool_args)}\n"
        f"Real error returned: {error_message}\n"
        f"{context}\n"
        f"Tool argument schema: {json.dumps(schema)}\n\n"
        "Propose corrected arguments as a JSON object matching the schema above that "
        "might succeed instead, based on the real error. If you cannot improve on the "
        "original arguments (the error isn't something adjusting arguments would fix), "
        "return the original arguments unchanged. Return ONLY a JSON object, no other text."
    )
    try:
        raw = await invoke_llm(
            [SystemMessage(content="You output ONLY a JSON object, no prose, no markdown fences."),
             HumanMessage(content=prompt)],
            tenant_id=tenant_id, user_id=user_id, task_id=task_id, request_type="task_step_adapt",
        )
        text = raw.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        adapted = json.loads(text)
        if isinstance(adapted, dict):
            return adapted
    except Exception:
        pass
    return tool_args


async def _call_tool(
    tenant_id: str, tool_name: str, tool_args: dict,
    user_id: str | None = None, task_id: str | None = None, agent_id: str | None = None,
) -> dict:
    """Invokes the real registered tool directly (not through the agent's
    ToolNode/LangGraph machinery -- there's no LLM reasoning a task step
    needs to trigger the call itself, the plan already decided that).
    tenant_id is force-injected here, same convention agent_node uses for
    real chat tool calls -- never trusted from tool_args.

    user_id/task_id/agent_id are injected the same way, but conditionally:
    unlike tenant_id (every registered tool declares it, by hard rule),
    most tools don't accept these at all, and merging an argument a tool's
    schema doesn't declare would break its own ainvoke() validation. Only
    inject when the target tool's own schema actually asks for it -- this
    makes the convention generic, not tool-specific: any future tool that
    adds a user_id/task_id/agent_id parameter gets it force-injected here
    automatically, with no further change to this function. agent_id
    (Wunomo Projects Phase 2, item 5) is the calling agent's real identity,
    used by the source-lock-aware tools to label a lock's holder."""
    tool_obj = tool_by_name(tool_name)
    call_args = {**tool_args, "tenant_id": tenant_id}
    if "user_id" in tool_obj.args:
        call_args["user_id"] = user_id
    if "task_id" in tool_obj.args:
        call_args["task_id"] = task_id
    if "agent_id" in tool_obj.args:
        call_args["agent_id"] = agent_id
    result = await tool_obj.ainvoke(call_args)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}
    return result


def _outcome_summary(tool_name: str, result: dict) -> str:
    """Capped, human-readable summary -- this, not the raw result, is
    what a resumed/adjacent step's context replays (amendment 2)."""
    text = json.dumps(result)
    if len(text) > 500:
        text = text[:500] + "...(truncated)"
    return f"{tool_name} succeeded: {text}"


def _looks_like_async_dispatch(tool_name: str, result: dict) -> bool:
    """True only for a real, recognized dispatch shape -- never a guess
    based on generic keys, since a false positive here would insert a
    verify step that can never resolve."""
    if tool_name == "run_pipeline" and isinstance(result, dict):
        return result.get("status") == RunStatus.PENDING and bool(result.get("run_id"))
    return False


async def _poll_dispatch_status(tool_name: str, dispatch_result: dict) -> dict:
    """Checks the REAL current state of a previously-dispatched operation.
    Returns {"terminal": bool, "success": bool | None, "detail": str}."""
    if tool_name == "run_pipeline":
        from models.all_models import PipelineRun
        run_id = dispatch_result.get("run_id")
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = r.scalar_one_or_none()
        if run is None:
            return {"terminal": True, "success": False, "detail": f"Run {run_id} record no longer exists."}
        if run.status == RunStatus.SUCCESS:
            return {"terminal": True, "success": True, "detail": f"Run {run_id} completed successfully."}
        if run.status == RunStatus.FAILED:
            return {"terminal": True, "success": False, "detail": f"Run {run_id} failed: {run.error_message}"}
        return {"terminal": False, "success": None, "detail": f"Run {run_id} is still {run.status}."}
    return {"terminal": True, "success": True, "detail": "Unrecognized dispatch type; treated as resolved."}


def _set_task_status_unless_cancelled(task: Task, new_status: TaskStatus) -> bool:
    """The one guard that makes cancel_task() mean something: a step
    already in flight when cancellation is requested cannot be
    interrupted (there's no cooperative-cancellation plumbing here, and a
    concurrent DB write can't stop an already-running `await`), so it
    runs to completion and its own real outcome is still honestly
    recorded -- but that completion must never silently overwrite a
    task-level CANCELLED back to RUNNING/COMPLETED/FAILED/etc. Every
    task.status write in this module goes through this function instead
    of a bare assignment. Returns whether the write was applied."""
    if task.status == TaskStatus.CANCELLED:
        return False
    task.status = new_status
    return True


def _check_wall_clock_cap(task: Task) -> str | None:
    """Bounds real execution exposure, not raw calendar time since
    started_at -- item 72 (WALKTHROUGH_FINDINGS_2026-08.md): a task
    approved more than MAX_TASK_WALL_CLOCK_HOURS after it started used
    to be killed the instant it was approved, undoing the approval that
    was just granted. task.paused_seconds (accumulated at every
    pause->RUNNING transition -- see the two call sites that increment
    it) is subtracted here, so time spent waiting on a human/quota/lock
    is free, exactly like the walk-away feature this cap has to coexist
    with requires."""
    if task.started_at is None:
        return None
    raw_elapsed_seconds = (datetime.utcnow() - task.started_at).total_seconds()
    paused_seconds = task.paused_seconds or 0
    elapsed_hours = (raw_elapsed_seconds - paused_seconds) / 3600
    if elapsed_hours > MAX_TASK_WALL_CLOCK_HOURS:
        return (
            f"Stopped: exceeded the {MAX_TASK_WALL_CLOCK_HOURS}-hour wall-clock execution budget "
            f"(started at {task.started_at.isoformat()}, {elapsed_hours:.1f}h of active execution "
            f"excluding {paused_seconds / 3600:.1f}h spent paused for approval/quota/a source lock)."
        )
    return None


def _check_step_budget_cap(task: Task) -> str | None:
    used = task.step_budget_used or 0
    if used >= task.step_budget_max:
        return f"Stopped: exceeded the {task.step_budget_max}-step budget (used {used}/{task.step_budget_max})."
    return None


def _check_for_loop(all_steps: dict) -> str | None:
    """A "loop" in this execution model can only mean the PLAN itself
    contains the same (tool, args) pair repeated with no real reason --
    steps are fixed at plan time, nothing re-plans mid-execution the way
    a live agent conversation might. Counts ALL occurrences, not just
    already-attempted ones -- a plan authored with 3 identical steps is
    already a bad plan before any of them run; waiting for 2 real wasted
    attempts before catching the 3rd would defeat the point. Excludes
    SYSTEM_INSERTED verify steps: every one of them shares the same empty
    tool_args ({}) by construction (see the dispatching-step success
    branch above), so 3 legitimate, different real dispatches would
    otherwise collide into a false positive -- this check is about
    whether the AUTHORED plan repeats itself, not system bookkeeping."""
    counts: dict[tuple, int] = {}
    for s in all_steps.values():
        if not s.tool_name or s.source == TaskStepSource.SYSTEM_INSERTED:
            continue
        sig = (s.tool_name, json.dumps(s.tool_args or {}, sort_keys=True))
        counts[sig] = counts.get(sig, 0) + 1
    for (tool_name, args_json), count in counts.items():
        if count >= LOOP_DETECTION_THRESHOLD:
            return (
                f"Stopped: detected a loop — '{tool_name}' called {count} times with "
                f"materially the same arguments ({args_json}) and no progress."
            )
    return None


async def _notify_task_stopped(task: Task, title: str, message: str, severity: str = "medium") -> None:
    """Stage 7: 'give it a task and walk away' only works if something
    tells you when it's done or needs you. Fires at the transitions that
    genuinely warrant it -- every terminal state, plus mid-task approval
    (someone needs to act) -- never for the retry-prone pauses
    (PAUSED_QUOTA_EXCEEDED, PAUSED_SOURCE_LOCKED) that self-heal via the
    beat tick and would otherwise spam on every failed attempt.

    PAUSED_FAILED_STEP is a partial exception (Wunomo Projects Phase 2
    frontend, slice 9): unlike the two pauses above, it never resolves on
    its own -- there is no resume path for it at all, for any cause. Its
    scope-denial cause specifically gets its own notification
    (_notify_scope_denial_once, below) because it has a real, one-action
    fix (grant the source) and a real reason to alert someone even though
    nobody's watching an unattended run; its other causes (attempt-budget
    exhaustion, the initiating user losing access) still don't notify
    here, matching the original reasoning -- they don't have an
    equally clean single fix to point someone at, and are rarer in
    practice than a scope gap recurring across several tasks.

    Best-effort, matching this module's own NotificationService contract:
    a delivery failure must never break the actual state transition it's
    describing."""
    try:
        from modules.reporting.notification_service import NotificationService
        await NotificationService(task.tenant_id).send_alert(
            channel="both", severity=severity, title=title, message=message,
            metadata={"task_id": task.id, "status": task.status.value},
        )
    except Exception as exc:
        log.warning("task_notification_failed", task_id=task.id, error=str(exc))


async def _notify_scope_denial_once(task: Task, scope_denial: dict) -> None:
    """One notification per distinct (agent, source) scope gap, not one
    per task (Wunomo Projects Phase 2 frontend, slice 9, explicit
    requirement) -- several tasks can independently hit the identical
    already-known gap (e.g. a recurring workflow needing a source that
    was never granted), and alerting once per task would mean N Slack
    messages for one real fix, the exact shape that gets a channel muted.
    Deduped via a real, visible Incident row -- the same dedup shape
    services/tasks.py's _check_freshness() already uses for stale
    sources: an OPEN incident for this exact cause is loaded and, if
    found, no new alert fires (the open incident IS the record); only a
    genuinely new (agent_id, source_id) pair creates one and alerts.

    The message names the fix (a real, absolute link to the agent's
    detail page) AND the consequence (this specific task can't resume
    even after the fix) -- a notification that says only "a task
    stopped" costs the same round trip through the app as no
    notification at all; one that says "grant access" without saying the
    paused task is already unrecoverable sends someone to fix the scope
    and then wait for a task that will never move (see finding 76)."""
    agent_id, source_id = scope_denial["agent_id"], scope_denial["source_id"]
    already_known = False
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Incident).where(
            Incident.tenant_id == task.tenant_id, Incident.status == IncidentStatus.OPEN,
            Incident.title.like("Scope gap:%"),
        ))
        for existing in r.scalars().all():
            if existing.affected_assets == [agent_id, source_id]:
                already_known = True
                break
        if not already_known:
            db.add(Incident(
                id=str(uuid.uuid4()), tenant_id=task.tenant_id,
                title=f"Scope gap: {scope_denial['agent_name']} → {scope_denial['source_name']}",
                description=scope_denial["message"], severity=IncidentSeverity.MEDIUM,
                affected_assets=[agent_id, source_id], detected_at=datetime.utcnow(),
            ))
            await db.commit()

    if already_known:
        return

    try:
        from config import settings
        from modules.reporting.notification_service import NotificationService
        grant_url = f"{settings.FRONTEND_URL}/agents/{agent_id}?highlight_source={source_id}"
        await NotificationService(task.tenant_id).send_alert(
            channel="both", severity="medium", title=f"Task paused — {scope_denial['agent_name']} denied access",
            message=(
                f"{scope_denial['agent_name']} doesn't have access to \"{scope_denial['source_name']}\" "
                f"(needed by \"{scope_denial['tool_name']}\") on task \"{task.goal}\". "
                f"Grant it here: {grant_url} — this task can't be resumed, so you'll need to start a new one."
            ),
            metadata={"task_id": task.id, "agent_id": agent_id, "source_id": source_id},
        )
    except Exception as exc:
        log.warning("scope_denial_notification_failed", task_id=task.id, error=str(exc))


async def execute_next_step(task_id: str) -> dict:
    """Thin locking wrapper -- see _execute_next_step_locked for the real
    logic. Wraps the ENTIRE call (not just the DB reads) in a per-task
    advisory lock (services/task_lock.py, item 73): two concurrent calls
    on the same task_id -- a beat tick and a human's /advance click, two
    overlapping ticks, or just two overlapping human clicks, which could
    already race before auto-advance ever existed -- can otherwise both
    read the same step as PENDING before either commits, and both call
    that step's tool. The lock is held for the full duration of the real
    call below, including its internal retry-backoff sleeps, so a denied
    caller gets {"outcome": "task_busy"} immediately rather than racing."""
    from services.task_lock import acquire_task_lock, TaskLockHeld
    try:
        async with acquire_task_lock(task_id):
            return await _execute_next_step_locked(task_id)
    except TaskLockHeld:
        return {"outcome": "task_busy"}


async def _execute_next_step_locked(task_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status not in RUNNABLE_TASK_STATUSES:
            return {"outcome": "not_runnable", "status": task.status.value}

        if task.status in (TaskStatus.QUEUED, TaskStatus.PAUSED_QUOTA_EXCEEDED, TaskStatus.PAUSED_SOURCE_LOCKED):
            # paused_seconds only accumulates for a status that was
            # actually a pause (QUEUED never was -- nothing to subtract
            # for a task that hasn't started yet, and its paused_at is
            # always None here).
            if task.status in (TaskStatus.PAUSED_QUOTA_EXCEEDED, TaskStatus.PAUSED_SOURCE_LOCKED) and task.paused_at is not None:
                task.paused_seconds = (task.paused_seconds or 0) + int(
                    (datetime.utcnow() - task.paused_at).total_seconds()
                )
            _set_task_status_unless_cancelled(task, TaskStatus.RUNNING)
            task.started_at = task.started_at or datetime.utcnow()
            await db.commit()

        r = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
        all_steps = {s.step_index: s for s in r.scalars().all()}

        # --- Termination caps (Q4), checked before any new work happens
        # this call. Each produces a distinguishable real reason, not just
        # "task stopped" -- FAILED is reused (was otherwise unused by this
        # module) for all three; PAUSED_QUOTA_EXCEEDED (credit exhaustion)
        # is handled separately, inside the attempt loop below, since it's
        # resumable rather than terminal. ---
        wall_clock_reason = _check_wall_clock_cap(task)
        if wall_clock_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = wall_clock_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", wall_clock_reason, severity="high")
            return {"outcome": "terminated_wall_clock", "reason": wall_clock_reason}

        step_budget_reason = _check_step_budget_cap(task)
        if step_budget_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = step_budget_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", step_budget_reason, severity="high")
            return {"outcome": "terminated_step_budget", "reason": step_budget_reason}

        loop_reason = _check_for_loop(all_steps)
        if loop_reason:
            _set_task_status_unless_cancelled(task, TaskStatus.FAILED)
            task.termination_reason = loop_reason
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(task, "Task stopped", loop_reason, severity="high")
            return {"outcome": "terminated_loop_detected", "reason": loop_reason}

        # --- Priority 1: resolve a step that's already dispatched and
        # waiting on real-world confirmation (Q2). At most one call's
        # worth of work happens here before this function either returns
        # or falls through to try independent forward progress. ---
        verifying = next((s for s in all_steps.values() if s.status == TaskStepStatus.VERIFYING), None)
        verify_elapsed = None
        if verifying is not None:
            poll = await _poll_dispatch_status(verifying.tool_name, verifying.raw_result or {})
            verifying.attempt_count = (verifying.attempt_count or 0) + 1
            verify_elapsed = (datetime.utcnow() - verifying.started_at).total_seconds() if verifying.started_at else 0.0

            if poll["terminal"] and poll["success"]:
                verifying.status = TaskStepStatus.SUCCEEDED
                verifying.outcome_summary = poll["detail"]
                verifying.completed_at = datetime.utcnow()
                await db.commit()
                return {"outcome": "step_verified_succeeded", "step_id": verifying.id, "detail": poll["detail"]}

            if poll["terminal"] and not poll["success"]:
                verifying.status = TaskStepStatus.FAILED
                verifying.error_message = poll["detail"]
                verifying.completed_at = datetime.utcnow()
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "step_verification_failed", "step_id": verifying.id, "reason": poll["detail"]}

            # Not yet terminal -- persist the poll attempt either way, then
            # decide below whether anything independent can still proceed
            # in this same call (the "move on" path), or whether this is
            # genuinely the only thing left (handled after the pending-step
            # search finds nothing runnable).
            await db.commit()

        # --- Priority 2: make progress on a runnable PENDING step, "move
        # on" from an unresolved verify step per Q2 whenever independent
        # work exists rather than blocking on it needlessly. ---
        pending = sorted(
            (s for s in all_steps.values() if s.status == TaskStepStatus.PENDING),
            key=lambda s: s.step_index,
        )
        step = None
        for candidate in pending:
            dep = candidate.depends_on_step_index
            if dep is None or (dep in all_steps and all_steps[dep].status == TaskStepStatus.SUCCEEDED):
                step = candidate
                break

        if step is None:
            # Nothing independent to run. Either genuinely done, still
            # honestly waiting on verification, or stuck on a dependency.
            if verifying is not None:
                if verify_elapsed is not None and verify_elapsed > VERIFY_TIMEOUT_SECONDS:
                    # The ONLY invariant that matters here: this branch is
                    # the sole path into COMPLETED_WITH_UNCONFIRMED_STEPS,
                    # and plain COMPLETED below is only reachable when
                    # `verifying` was None to begin with -- a task can
                    # never report clean success while a dispatched step
                    # remains unconfirmed.
                    _set_task_status_unless_cancelled(task, TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS)
                    task.completed_at = datetime.utcnow()
                    await db.commit()
                    await _notify_task_stopped(
                        task, "Task completed with unconfirmed steps",
                        f'Step {verifying.step_index} ("{verifying.description}") could not be confirmed '
                        f"within the verification window.", severity="medium",
                    )
                    return {
                        "outcome": "task_completed_with_unconfirmed_steps",
                        "step_id": verifying.id, "elapsed_seconds": verify_elapsed,
                    }
                await db.commit()
                return {"outcome": "still_verifying", "step_id": verifying.id, "elapsed_seconds": verify_elapsed}
            if pending:
                # Every remaining pending step is blocked on a dependency
                # that never succeeded -- shouldn't be reachable given we
                # pause the whole task on the first real failure, but
                # guarded rather than assumed.
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "blocked_on_dependency"}
            _set_task_status_unless_cancelled(task, TaskStatus.COMPLETED)
            task.completed_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(
                task, "Task completed", f'Task "{task.goal}" completed successfully.', severity="low",
            )
            return {"outcome": "task_completed"}

        authorized, denial_reason, scope_denial = await _caller_still_authorized(db, task, step.tool_name, step.tool_args or {})
        if not authorized:
            step.attempt_count += 1
            step.status = TaskStepStatus.FAILED
            step.error_message = f"Blocked: {denial_reason}."
            step.started_at = step.started_at or datetime.utcnow()
            step.completed_at = datetime.utcnow()
            _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
            await db.commit()
            if scope_denial is not None:
                await _notify_scope_denial_once(task, scope_denial)
            return {
                "outcome": "blocked_permission", "step_id": step.id,
                "attempt_count": step.attempt_count, "reason": denial_reason,
            }

        # Mid-task approval gate (Q5): risk tier is read from the same
        # RISK_ACTIONS map chat's own approval gate uses (agent/
        # personality.py) -- one source of truth, not a parallel
        # classification a task could silently drift from. Tasks have no
        # operation_mode concept (there's no human present each turn to
        # have granted one), so gating is unconditional on tier: medium
        # or high always requires approval, low never does.
        if get_risk_level(step.tool_name) in ("medium", "high") and step.approval_request_id is None:
            # Tier 1 resolution — must happen before the ApprovalRequest is
            # created, not after: what gets displayed on the approval card
            # (action_args below, and the same TaskStep row the step-
            # timeline table renders) has to already be the real, final
            # value the tool will actually be called with. Resolving later
            # (e.g. lazily in resume_task) would mean approving one thing
            # and executing another. Guarded by approval_request_id is None
            # above (this whole block only runs once per step, ever) and
            # by risk tier here in _resolve_step_args's sibling call below
            # — together these guarantee a step's args are resolved
            # exactly once, never re-touched on a resume.
            if step.source != TaskStepSource.HUMAN_EDITED:
                step.tool_args = await _resolve_step_args(db, task_id, step)
            approval = await PolicyEngine(task.tenant_id).create_request(
                user_id=task.user_id, session_id=task.id, action_name=step.tool_name,
                action_args=step.tool_args or {}, risk_level=get_risk_level(step.tool_name),
                reason=f'Task step "{step.description}" requires approval before it can run.',
            )
            step.approval_request_id = approval["approval_id"]
            step.status = TaskStepStatus.BLOCKED_APPROVAL
            _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_NEEDS_APPROVAL)
            task.paused_at = datetime.utcnow()
            await db.commit()
            await _notify_task_stopped(
                task, "Task needs approval",
                f'Step {step.step_index} ("{step.description}") needs approval to run "{step.tool_name}".',
                severity="medium",
            )
            return {
                "outcome": "blocked_needs_approval", "step_id": step.id,
                "approval_request_id": approval["approval_id"], "risk_level": approval["risk_level"],
            }

        if step.approval_request_id is not None:
            r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
            approval_req = r.scalar_one_or_none()
            if approval_req is None or approval_req.status == ApprovalStatus.PENDING:
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_NEEDS_APPROVAL)
                await db.commit()
                return {"outcome": "still_blocked_needs_approval", "step_id": step.id}
            if approval_req.status == ApprovalStatus.REJECTED:
                step.status = TaskStepStatus.FAILED
                step.error_message = f"Step rejected: {approval_req.resolution_note or 'no reason given'}."
                step.completed_at = datetime.utcnow()
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
                return {"outcome": "step_rejected", "step_id": step.id, "reason": step.error_message}
            # APPROVED (or, defensively, any other resolved state) -- fall
            # through to real execution below. This is the resume path:
            # the tool call that follows is a genuine, fresh call -- not a
            # cached replay -- so it re-validates its own preconditions
            # and, one line above, _caller_still_authorized() already
            # re-validated the initiating user's authority for real.

        # Tier 1 resolution for auto-run (low-risk) steps — the sibling of
        # the approval-gate call above. Explicitly excludes medium/high
        # risk here (rather than relying on "they never reach this branch
        # unresolved" implicitly) so a step's args are resolved at exactly
        # one of these two call sites, never both: a medium/high-risk step
        # was already resolved before its approval card rendered, and must
        # not be silently re-resolved on the resume pass just because it
        # happens to also have attempt_count == 0 here.
        if (
            (step.attempt_count or 0) == 0
            and get_risk_level(step.tool_name) not in ("medium", "high")
            and step.source != TaskStepSource.HUMAN_EDITED
        ):
            step.tool_args = await _resolve_step_args(db, task_id, step)

        step.status = TaskStepStatus.RUNNING
        step.started_at = step.started_at or datetime.utcnow()
        tenant_id, task_user_id, agent_id = task.tenant_id, task.user_id, task.agent_id
        tool_name, tool_args, step_id = step.tool_name, dict(step.tool_args or {}), step.id
        description = step.description
        # Resuming after a credit-exhaustion pause continues the SAME
        # attempt budget rather than granting a fresh 3 -- attempt_count
        # already reflects any attempt that happened before the pause
        # (see the quota_paused branch below).
        starting_attempt = (step.attempt_count or 0) + 1
        # Tier 2 fallback context (see _adapt_step_args) -- gathered here,
        # inside the transaction, since the attempt loop below runs
        # outside any DB session. Only earlier steps that actually
        # succeeded, in order; a step still PENDING/FAILED has nothing
        # trustworthy to contribute.
        prior_results = [
            {"step_index": s.step_index, "tool_name": s.tool_name, "result": s.raw_result}
            for s in sorted(all_steps.values(), key=lambda s: s.step_index)
            if s.status == TaskStepStatus.SUCCEEDED and s.step_index < step.step_index
        ]
        await db.commit()

    # The attempt loop runs outside any single DB transaction -- each
    # tool call and the (possible) LLM-adapt call open their own sessions
    # internally, matching this codebase's established pattern.
    last_error = None
    adapted_once = False
    quota_paused_attempt = None
    source_locked_paused_attempt = None
    current_args = tool_args
    for attempt in range(starting_attempt, MAX_ATTEMPTS_PER_STEP + 1):
        # Scope re-check (Wunomo Projects Phase 1), immediately before the
        # real tool call -- this is THE enforcement point, not a cost
        # optimisation (see CLAUDE.md's plan-time-vs-enforcement split):
        # current_args is always fully resolved by the time execution
        # reaches here, whichever tier resolved it (Tier 1 discovery-pool
        # match, Tier 2 LLM-adapt, or HUMAN_EDITED). Re-checked on every
        # attempt, not just the first, because Tier 2 adaptation can
        # redirect current_args at a different, out-of-scope entity
        # between attempts -- a real, current id always exists here, so
        # there's no "placeholder, nothing to check yet" case to worry
        # about the way _caller_still_authorized's own scope check does.
        async with AsyncSessionLocal() as scope_db:
            scope_denial = await agent_scope_denial_reason(scope_db, agent_id, tool_name, current_args)
        if scope_denial is not None:
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
                step = r.scalar_one()
                step.attempt_count = attempt
                step.status = TaskStepStatus.FAILED
                step.error_message = f"Blocked: {scope_denial['message']}"
                step.completed_at = datetime.utcnow()

                r = await db.execute(select(Task).where(Task.id == task_id))
                task = r.scalar_one()
                _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
                await db.commit()
            await _notify_scope_denial_once(task, scope_denial)
            return {
                "outcome": "blocked_permission", "step_id": step_id,
                "attempt_count": attempt, "reason": scope_denial["message"],
            }

        try:
            result = await _call_tool(
                tenant_id, tool_name, current_args, user_id=task_user_id, task_id=task_id, agent_id=agent_id,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_ATTEMPTS_PER_STEP:
                await asyncio.sleep(TRANSIENT_RETRY_BACKOFF_SECONDS)
            continue

        if isinstance(result, dict) and result.get("error"):
            last_error = str(result["error"])
            if result.get("lock_conflict"):
                # A source lock conflict (Wunomo Projects Phase 2, item 5)
                # is not a domain error to adapt around -- current_args
                # are already correct, the resource is just busy -- and
                # not a quota exhaustion either. Pause immediately,
                # regardless of attempt count or adapted_once, using the
                # same pause/resume shape as quota_paused_attempt: the
                # step goes back to PENDING (not FAILED), so resumption
                # retries with the same attempt budget once the lock frees,
                # rather than burning an attempt/adapt cycle racing it.
                source_locked_paused_attempt = attempt
                break
            if attempt < MAX_ATTEMPTS_PER_STEP and not adapted_once:
                # Credit exhaustion pauses the task instead of silently
                # degrading to an unadapted retry (Q4) -- the only real
                # LLM spend anywhere in step execution is this adapt call,
                # so this is the one place quota needs to be checked.
                # Two-gate (Wunomo Projects Phase 1, part two): the
                # tenant-level check existed first; the agent-level one
                # is the second, independent gate -- either exceeded
                # pauses the task the same way, and last_error is
                # overwritten so the pause reason names the actual gate
                # that blocked it, not the stale domain error from the
                # tool call that triggered this adapt attempt.
                quota = await get_quota_status(tenant_id, "ai_credits")
                if quota["status"] == "exceeded":
                    last_error = "Paused: the tenant's AI-credit quota is exhausted for this billing period."
                    quota_paused_attempt = attempt
                    break
                agent_quota = await get_agent_quota_status(agent_id) if agent_id else {"status": "ok"}
                if agent_quota["status"] == "exceeded":
                    last_error = (
                        f"Paused: this agent's monthly token budget "
                        f"({agent_quota['used']}/{agent_quota['limit']} tokens) is exhausted."
                    )
                    quota_paused_attempt = attempt
                    break
                adapted_args = await _adapt_step_args(
                    tenant_id, task_user_id, description, tool_name, current_args, last_error,
                    prior_results=prior_results, task_id=task_id,
                )
                async with AsyncSessionLocal() as guard_db:
                    current_args = await _reject_ungrounded_adaptation(
                        guard_db, task_id, current_args, adapted_args,
                    )
                adapted_once = True
            continue

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
            step = r.scalar_one()
            step.status = TaskStepStatus.SUCCEEDED
            step.attempt_count = attempt
            step.tool_args = current_args
            step.raw_result = result
            step.outcome_summary = _outcome_summary(tool_name, result)
            step.completed_at = datetime.utcnow()

            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one()
            task.step_budget_used = (task.step_budget_used or 0) + 1

            outcome = {"outcome": "step_succeeded", "step_id": step_id, "attempt_count": attempt}

            if tool_name in _VERIFIABLE_TOOLS and _looks_like_async_dispatch(tool_name, result):
                # A genuinely new step, source=SYSTEM_INSERTED, appended
                # with a fresh unused step_index (existing steps are never
                # renumbered) and depending on the dispatching step's own
                # index -- never a status recycled onto the dispatching
                # step itself, so the timeline can always tell what AXIOM
                # planned from what the system added (amendment 3).
                r2 = await db.execute(select(func.max(TaskStep.step_index)).where(TaskStep.task_id == task_id))
                max_index = r2.scalar_one()
                verify_step = TaskStep(
                    id=str(uuid.uuid4()), task_id=task_id, step_index=(max_index or 0) + 1,
                    description=f'Verify that "{description}" reached a final state.',
                    source=TaskStepSource.SYSTEM_INSERTED,
                    tool_name=tool_name,  # what kind of dispatch to poll, not a tool to call again
                    tool_args={},
                    depends_on_step_index=step.step_index,
                    status=TaskStepStatus.VERIFYING,
                    raw_result=result,  # carries run_id etc. -- what _poll_dispatch_status reads
                    started_at=datetime.utcnow(),
                )
                db.add(verify_step)
                await db.flush()
                outcome["outcome"] = "step_dispatched_pending_verification"
                outcome["verify_step_id"] = verify_step.id

            await db.commit()

        return outcome

    if quota_paused_attempt is not None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
            step = r.scalar_one()
            # This attempt genuinely happened and hit a real domain error
            # -- it counts. Back to PENDING (not FAILED): resuming picks up
            # at starting_attempt = attempt_count + 1, the SAME budget,
            # never a fresh 3.
            step.attempt_count = quota_paused_attempt
            step.error_message = last_error
            step.status = TaskStepStatus.PENDING

            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one()
            if _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_QUOTA_EXCEEDED):
                task.paused_at = datetime.utcnow()
            await db.commit()

        return {
            "outcome": "paused_quota_exceeded", "step_id": step_id,
            "attempt_count": quota_paused_attempt, "reason": last_error,
        }

    if source_locked_paused_attempt is not None:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
            step = r.scalar_one()
            # Same shape as the quota_paused_attempt branch above: back to
            # PENDING (not FAILED), resuming picks up at
            # starting_attempt = attempt_count + 1, the SAME budget.
            step.attempt_count = source_locked_paused_attempt
            step.error_message = last_error
            step.status = TaskStepStatus.PENDING

            r = await db.execute(select(Task).where(Task.id == task_id))
            task = r.scalar_one()
            if _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_SOURCE_LOCKED):
                task.paused_at = datetime.utcnow()
            await db.commit()

        return {
            "outcome": "paused_source_locked", "step_id": step_id,
            "attempt_count": source_locked_paused_attempt, "reason": last_error,
        }

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(TaskStep).where(TaskStep.id == step_id))
        step = r.scalar_one()
        # Commit 4: honest failure messaging. The raw tool error ("Source
        # not found") blames the entity for not existing, when the real
        # problem was often that the argument sent to look it up was never
        # a real value to begin with — checked against the same evidence
        # resolution itself used, not guessed.
        note = await _unresolved_reference_note(db, task_id, step, current_args)
        step.status = TaskStepStatus.FAILED
        step.attempt_count = MAX_ATTEMPTS_PER_STEP
        step.error_message = f"{note} Real error: {last_error}" if note else last_error
        step.completed_at = datetime.utcnow()

        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one()
        _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
        await db.commit()

    return {
        "outcome": "step_failed", "step_id": step_id,
        "attempt_count": MAX_ATTEMPTS_PER_STEP, "reason": step.error_message,
    }


def _is_approval_expired(task: Task) -> bool:
    if task.paused_at is None:
        return False
    elapsed_hours = (datetime.utcnow() - task.paused_at).total_seconds() / 3600
    return elapsed_hours > APPROVAL_PAUSE_TIMEOUT_HOURS


async def resume_task(task_id: str, resolved_by: str, notes: str = "") -> dict:
    """Approves the blocked step's ApprovalRequest, then re-enters the
    normal execution pipeline for real -- this is deliberately NOT a
    special "continue" code path with its own logic. Everything that
    makes resume safe falls out of execute_next_step()'s existing,
    already-proven behavior: _caller_still_authorized() re-validates the
    initiating user's role/is_active fresh (Q5's authority requirement),
    and the tool call that follows is a genuine new call, not a cached
    replay, so it re-validates its own real-world preconditions (Q5's
    precondition requirement). Nothing here holds any in-memory state --
    a worker/backend restart between pause and resume changes nothing,
    since every fact this function reads comes from the DB."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
            return {"outcome": "not_resumable", "status": task.status.value}

        if _is_approval_expired(task):
            _set_task_status_unless_cancelled(task, TaskStatus.EXPIRED)
            await db.commit()
            await _notify_task_stopped(
                task, "Task expired",
                f'Task "{task.goal}" expired waiting for approval.', severity="medium",
            )
            return {"outcome": "expired"}

        r = await db.execute(
            select(TaskStep).where(
                TaskStep.task_id == task_id, TaskStep.status == TaskStepStatus.BLOCKED_APPROVAL,
            )
        )
        step = r.scalar_one_or_none()
        if step is None or step.approval_request_id is None:
            return {"outcome": "no_blocked_step"}

        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval_req = r.scalar_one()
        approval_req.status = ApprovalStatus.APPROVED
        approval_req.resolved_by = resolved_by
        approval_req.resolved_at = datetime.utcnow()
        approval_req.resolution_note = notes

        if task.paused_at is not None:
            task.paused_seconds = (task.paused_seconds or 0) + int(
                (datetime.utcnow() - task.paused_at).total_seconds()
            )
        step.status = TaskStepStatus.PENDING
        _set_task_status_unless_cancelled(task, TaskStatus.RUNNING)
        await db.commit()

    return await execute_next_step(task_id)


async def reject_task_step(task_id: str, resolved_by: str, notes: str = "") -> dict:
    """Declines the blocked step outright -- no re-entry into execution,
    since there's nothing to re-attempt. Reuses the existing
    PAUSED_FAILED_STEP pause/pause_reason machinery rather than inventing
    a parallel one for "rejected" specifically."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
            return {"outcome": "not_resumable", "status": task.status.value}

        if _is_approval_expired(task):
            _set_task_status_unless_cancelled(task, TaskStatus.EXPIRED)
            await db.commit()
            await _notify_task_stopped(
                task, "Task expired",
                f'Task "{task.goal}" expired waiting for approval.', severity="medium",
            )
            return {"outcome": "expired"}

        r = await db.execute(
            select(TaskStep).where(
                TaskStep.task_id == task_id, TaskStep.status == TaskStepStatus.BLOCKED_APPROVAL,
            )
        )
        step = r.scalar_one_or_none()
        if step is None or step.approval_request_id is None:
            return {"outcome": "no_blocked_step"}

        r = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == step.approval_request_id))
        approval_req = r.scalar_one()
        approval_req.status = ApprovalStatus.REJECTED
        approval_req.resolved_by = resolved_by
        approval_req.resolved_at = datetime.utcnow()
        approval_req.resolution_note = notes

        step.status = TaskStepStatus.FAILED
        step.error_message = f"Step rejected: {notes or 'no reason given'}."
        step.completed_at = datetime.utcnow()
        _set_task_status_unless_cancelled(task, TaskStatus.PAUSED_FAILED_STEP)
        await db.commit()

    return {"outcome": "step_rejected", "step_id": step.id}


_NON_CANCELLABLE_STATUSES = (
    TaskStatus.COMPLETED, TaskStatus.COMPLETED_WITH_UNCONFIRMED_STEPS,
    TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PLAN_REJECTED, TaskStatus.EXPIRED,
)


async def cancel_task(task_id: str, cancelled_by: str) -> dict:
    """Marks the task CANCELLED immediately. Honest about what this can
    and cannot do: a step already in flight (its tool call already
    started in a concurrent request) cannot be interrupted -- there is no
    cooperative-cancellation plumbing in this codebase, and a plain DB
    write from a separate request has no way to stop an already-running
    `await` somewhere else. What IS guaranteed: every place
    execute_next_step() finishes a step goes through
    _set_task_status_unless_cancelled() before writing Task.status, so a
    step that finishes AFTER this call still gets its own real,
    factual outcome recorded (it may have genuinely succeeded), but the
    task-level status can never be silently stomped back from CANCELLED
    to RUNNING/COMPLETED/etc. -- see CLAUDE.md for the live-proved race."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if task is None:
            return {"outcome": "task_not_found"}
        if task.status in _NON_CANCELLABLE_STATUSES:
            return {"outcome": "not_cancellable", "status": task.status.value}

        was_running = task.status == TaskStatus.RUNNING
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        task.termination_reason = (
            f"Cancelled by user {cancelled_by}."
            + (
                " A step may have been executing at the moment cancellation was requested; it "
                "cannot be interrupted mid-flight and may have completed after this task was "
                "cancelled -- check each step's own status for what actually happened."
                if was_running else ""
            )
        )
        await db.commit()
        await _notify_task_stopped(task, "Task cancelled", task.termination_reason, severity="low")

    return {"outcome": "cancelled"}
