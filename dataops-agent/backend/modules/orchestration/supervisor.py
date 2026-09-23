"""Stage 2, part 1 (multi-agent supervisor) -- docs/design/wunomo-blueprint.html
§20 "Stage 2 -- the supervisor and the handoff". Headless only: nothing in
this module is wired into any HTTP route yet (see api/v1/channels.py /
api/v1/chat.py for the eventual wiring) -- every entry point here is meant
to be called directly, the way the tests in tests/test_supervisor.py do.

WHAT THIS DOES NOT DO (honest, deliberate scope, not an oversight):
  - No fan-in, still. depends_on_task_id (models/all_models.py) is a
    single self-referential FK, not an edge table -- a task can wait on
    at most one predecessor. Originally this made fan-in structurally
    impossible for the regex heuristic to even propose; now that an LLM
    proposes edges (see infer_dependencies below), it genuinely CAN
    return more than one predecessor for a node -- plan_node detects
    that explicitly and refuses to dispatch (zero Task rows), rather than
    silently dropping one edge or linearizing an order nobody asked for.
    Generalizing the schema itself to real fan-in is still out of scope.
  - No re-planning mid-run. The blueprint's own failure-semantics table
    lists "user sends a new message mid-run -> parsed against current
    state, ask rather than guess" as a required behavior; this module
    only implements one full parse->plan->dispatch->run->handoff pass per
    call. A second concurrent message against the same channel while
    tasks are in flight is not handled here.
  - DAG inference is a deterministic fast path (an exhaustive pairwise
    possessive-reference check, run first and for free) in front of a
    structured LLM call (infer_dependencies, mirroring task_planner.py's
    generate_plan() pattern exactly) for whatever the fast path couldn't
    resolve. See the module-level report this was shipped with for what
    the LLM leg catches that the old regex-only version missed, where
    it's the weaker choice, and how a low/medium-confidence or outright-
    failed inference degrades to asking rather than guessing
    (needs_clarification) -- a planner OUTAGE specifically degrades to
    "keep every fast-path edge, ask only about what still needed the LLM"
    (partial dispatch), never a blanket refusal of the whole message.

WHY SUPERVISOR-DISPATCHED TASKS NEVER TOUCH task_executor.py:
A SUPERVISOR_INTENT task is one free-form instruction ("summarise this
file"), not an LLM-planned sequence of tool calls -- there is nothing for
task_planner.py to plan and nothing for task_executor.py's step-dispatch
loop to execute. The run node instead calls run_agent()
(agent/dataops_agent.py) directly and unchanged -- the exact function
POST /api/v1/chat/ itself calls -- once per ready task. The per-agent
graph, its tools, its approval gate, and its get_agent() cache are all
untouched by this file.

WHY TWO NEW TaskStatus VALUES (SUPERVISOR_QUEUED/SUPERVISOR_RUNNING),
NOT THE EXISTING QUEUED/RUNNING:
services/tasks.py's advance_active_tasks beat tick -- live, in every
environment, every 60s -- polls Task.status.in_(RUNNABLE_TASK_STATUSES)
with no task_shape filter. If a supervisor task ever held a status in
that tuple, the beat tick would hand it to task_executor.py, which
expects a step this task_shape never has. See models/all_models.py's own
comment on RUNNABLE_TASK_STATUSES for the full reasoning.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

import structlog

from agent.dataops_agent import _finalize_agent_result, run_agent, run_agent_stream
from database import AsyncSessionLocal
from models.all_models import (
    AgentInstance, Channel, ChatMessage, Handoff, Task, TaskShape, TaskStatus, TaskStep,
    TaskStepSource, TaskStepStatus, User,
)
from models.approval_model import ApprovalRequest
from services.channel_routing import find_active_agent_in_tenant, resolve_mentioned_agent
from services.llm_service import invoke_llm
from services.tenant_context import async_tenant_context
from services import pii_classifier, prompt_guard

# One live-progress callback signature, shared by every node/helper below
# that can emit a mid-run SSE-shaped event: (event_type, data) -> None.
# None (the default everywhere) means "no one is listening live" -- exactly
# retry_task()'s and resolve_task_approval()'s own situation, since both
# run well after the originating HTTP request already returned. Only
# api/v1/chat.py's _run_supervisor_and_stream passes a real one, wired
# straight to its SSE queue.
EventSink = Callable[[str, dict], Awaitable[None]] | None


async def _emit(sink: EventSink, event_type: str, data: dict) -> None:
    if sink is not None:
        await sink(event_type, data)

log = structlog.get_logger()

# DAG-level ceiling (failure-semantics table's own requirement), separate
# from Task.step_budget_max (which bounds steps WITHIN one task). Bounds
# how many intents a single message can fan out into -- without this, one
# message mentioning many agents could dispatch an unbounded number of
# real Task rows from a single request.
MAX_DAG_TASKS = 8

# One TaskStep per SUPERVISOR_INTENT task -- a single free-form
# instruction is "one step" by construction, not a multi-step plan.
SUPERVISOR_TASK_STEP_BUDGET = 1

# Recognizes every @mention anywhere in the message, not just a leading
# one -- services/mentions.py's parse_mention() is deliberately v1-narrow
# ("exactly one mention per message... at the very start"), which is
# exactly what a multi-agent message violates by definition. A message's
# text between one mention and the next becomes that mention's own
# instruction.
_MENTION_TOKEN = re.compile(r"@(\S+)")


def parse_all_mentions(message: str) -> list[tuple[str, str]]:
    """Returns [(mentioned_name, instruction_text), ...] in message order.
    "@a summarise this file, then @b count the rows in a's summary." ->
    [("a", "summarise this file, then"), ("b", "count the rows in a's summary.")].
    A trailing punctuation character on the handle itself (a mention right
    before a comma) is stripped; punctuation inside the instruction text
    is left alone."""
    matches = list(_MENTION_TOKEN.finditer(message))
    results = []
    for i, m in enumerate(matches):
        name = m.group(1).rstrip(".,;:!?")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(message)
        text = message[start:end].strip()
        results.append((name, text))
    return results


class SupervisorState(TypedDict):
    tenant_id: str
    channel_id: str
    project_id: str | None
    user_id: str
    caller_role: str
    message: str
    intents: list[dict]
    unresolved_mentions: list[dict]
    edges: list[tuple[int, int]]
    inferred_edge_notices: list[str]
    error: str | None
    # Structured alongside `error`'s own free-text message -- added when
    # the chat route needed to classify a refusal for its SSE `error`
    # event without parsing message text (api/v1/chat.py's own "the
    # refusal kind (cycle / fan-in / ceiling)" requirement). One of
    # "ceiling" / "fan_in" / "cycle"; None whenever error is None.
    error_kind: str | None
    needs_clarification: list[dict] | None
    blocked_intent_indices: list[int]
    tasks: list[dict]
    completed_this_wave: list[str]
    handoffs_created: list[str]
    more_ready: bool
    # Not real graph state (never read by any node's routing/return value,
    # never serializable, never checkpointed -- this graph has no
    # checkpointer, see retry_task()'s own docstring on why re-entering
    # this module directly rather than resuming mid-graph is deliberate).
    # Threaded through purely so dispatch_node/run_node/_run_one_task can
    # reach the one live callback api/v1/chat.py's streaming route cares
    # about, without every node function growing its own extra parameter.
    event_sink: Any


# ---------------------------------------------------------------------
# Dependency planner -- a structured LLM call replacing the earlier regex
# heuristic (_references_agent_output), following task_planner.py's
# generate_plan() pattern exactly: build a prompt, call invoke_llm() (the
# existing timeout-fallback-wrapped service, never a bare LLM client),
# parse JSON, validate, retry once with a corrective reprompt on failure,
# raise a specific exception if it still can't produce a valid plan.
# ---------------------------------------------------------------------

_MAX_DEPENDENCY_PLANNING_ATTEMPTS = 2


class DependencyPlanningError(Exception):
    """The LLM call itself (or its output) never produced a valid
    dependency plan, even after the one corrective retry. plan_node
    catches this and degrades to needs_clarification -- never guesses
    "no dependency" just because the planner failed."""


class DependencyPlanValidationError(Exception):
    """A dependency plan response fails structural validation: wrong
    length, an unknown agent name, a self-reference, or a missing
    confidence where depends_on is non-empty."""


def _references_agent_output(text: str, agent_name: str) -> bool:
    """The deterministic fast path: an explicit possessive back-reference
    to another agent's name ("Nova's summary") in the same message. Free,
    instant, and -- unlike a bare name mention -- specific enough to
    trust on its own: every edge this finds is applied at HIGH confidence
    with NO LLM call at all. This is the same check Stage 2 originally
    shipped with (then named identically) before the LLM planner replaced
    it wholesale; it now runs FIRST, in front of the planner, rather than
    instead of it."""
    return re.search(rf"\b{re.escape(agent_name)}'s\b", text, re.IGNORECASE) is not None


def _mentions_agent_name(text: str, agent_name: str) -> bool:
    """A weaker signal than _references_agent_output -- a bare mention of
    another agent's name, with no possessive. Never used to assert a
    dependency by itself (a bare name is far too easy to trip on by
    coincidence); used only to decide whether an intent is worth an LLM
    call at all. An intent that doesn't mention any other agent by name
    anywhere has nothing for the LLM to find either -- the fast path
    already knows the answer ("no dependency") for free, and spending a
    call just to hear that back would be pure waste."""
    return re.search(rf"\b{re.escape(agent_name)}\b", text, re.IGNORECASE) is not None


def _build_dependency_prompt(message: str, intents: list[dict], pending_intents: list[dict]) -> str:
    agent_lines = []
    for intent in intents:
        description = intent.get("standing_instructions") or "No standing instructions set."
        agent_lines.append(
            f'- "{intent["agent_name"]}" ({intent["employee_type"]}): {description}\n'
            f'  Its instruction: "{intent["text"]}"'
        )
    pending_names = {p["agent_name"] for p in pending_intents}
    already_resolved = [i for i in intents if i["agent_name"] not in pending_names]
    names = ", ".join(f'"{p["agent_name"]}"' for p in pending_intents)

    prompt = (
        f'Original message: "{message}"\n\n'
        "This message was split into one instruction per @mentioned agent:\n"
        + "\n".join(agent_lines)
    )
    if already_resolved:
        resolved_names = ", ".join(f'"{i["agent_name"]}"' for i in already_resolved)
        prompt += (
            f"\n\nA separate, deterministic check already determined the dependency status of "
            f"{resolved_names} -- they are listed above only for context (one of the agents "
            "below may still depend on one of them); do not re-decide those."
        )
    prompt += (
        f"\n\nFor ONLY the following remaining agent(s) -- {names} -- decide whether its "
        "instruction depends on another agent's output before it can run -- i.e. can this "
        "agent's instruction only be carried out AFTER seeing what another agent produced?\n\n"
        "If the user explicitly said something like \"then\", \"once X is done\", or "
        "\"using X's output\", that dependency is HIGH confidence. If you are inferring a "
        "relationship without an explicit textual marker, rate your own confidence "
        "honestly: HIGH only if you are very sure, MEDIUM or LOW if there is real "
        "ambiguity. A wrong guess dispatched with false confidence is worse than asking a "
        "human to confirm the order -- do not round up to HIGH just to avoid a null.\n\n"
        f"Return a JSON array with exactly one object per agent, in this exact order: {names}.\n"
        'Each object: {"agent": "<agent name, exact>", "depends_on": [<zero or more other '
        "agent names this one needs output from first -- normally zero or one; only "
        "return more than one if this agent's instruction genuinely needs BOTH other "
        'agents\' output>], "confidence": "high"|"medium"|"low" (omit or null when '
        'depends_on is empty), "reason": "<one sentence explaining the dependency, or '
        'null when depends_on is empty>"}.\n'
        "Return ONLY the JSON array, no other text, no markdown fences."
    )
    return prompt


def _validate_dependency_plan(intents: list[dict], pending_intents: list[dict], parsed) -> list[dict]:
    if not isinstance(parsed, list) or len(parsed) != len(pending_intents):
        raise DependencyPlanValidationError(
            f"Expected a JSON array of exactly {len(pending_intents)} objects, one per pending agent; got {parsed!r}."
        )
    all_names = {i["agent_name"] for i in intents}
    pending_names = {i["agent_name"] for i in pending_intents}
    by_name: dict[str, dict] = {}
    for i, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise DependencyPlanValidationError(f"Entry {i}: must be an object.")
        agent = entry.get("agent")
        if agent not in pending_names:
            raise DependencyPlanValidationError(
                f"Entry {i}: agent {agent!r} is not one of the pending agents {sorted(pending_names)}."
            )
        if agent in by_name:
            raise DependencyPlanValidationError(f"Entry {i}: duplicate entry for agent {agent!r}.")

        depends_on = entry.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
            raise DependencyPlanValidationError(f"Entry {i}: depends_on must be a list of agent names.")
        unknown = [d for d in depends_on if d not in all_names]
        if unknown:
            raise DependencyPlanValidationError(f"Entry {i}: depends_on references unknown agent(s): {unknown}.")
        if agent in depends_on:
            raise DependencyPlanValidationError(f"Entry {i}: agent {agent!r} cannot depend on itself.")

        confidence = entry.get("confidence")
        if depends_on and confidence not in ("high", "medium", "low"):
            raise DependencyPlanValidationError(
                f"Entry {i}: confidence must be one of high/medium/low when depends_on is non-empty (got {confidence!r})."
            )

        by_name[agent] = {
            "agent": agent, "depends_on": depends_on, "confidence": confidence, "reason": entry.get("reason"),
        }

    return [by_name[i["agent_name"]] for i in pending_intents]


async def infer_dependencies(
    *, tenant_id: str, user_id: str, message: str, intents: list[dict],
    pending_intents: list[dict] | None = None,
) -> list[dict]:
    """Same shape as task_planner.py's generate_plan(): a system prompt
    demanding JSON-only output, invoke_llm() (never a bare LLM client --
    this goes through the same timeout-fallback wrapper and retry/usage-
    logging every other LLM call in this codebase does), one corrective
    retry on a malformed/invalid response, then a specific exception --
    never a partially-valid plan, never a silent empty result.

    Only asked to resolve `pending_intents` -- the subset plan_node's own
    fast path (an exhaustive possessive-reference check, run before this
    is ever called) found no edge for AND that still mentions some other
    agent's name at all. `intents` is passed in full regardless, purely
    for context, so the model understands what every other agent's
    instruction actually says. Defaults `pending_intents` to `intents`
    (i.e. "ask about everyone") when not given -- every call site outside
    plan_node's fast path, and every existing direct test of this
    function, relies on that default."""
    if pending_intents is None:
        pending_intents = intents
    system_prompt = (
        "You are Wunomo's multi-agent dependency planner. You output ONLY a JSON array "
        "matching the requested schema -- no prose, no markdown fences, no explanation."
    )
    user_prompt = _build_dependency_prompt(message, intents, pending_intents)
    last_error = None

    for attempt in range(_MAX_DEPENDENCY_PLANNING_ATTEMPTS):
        prompt = user_prompt if attempt == 0 else (
            f"{user_prompt}\n\nYour previous response was invalid: {last_error}. "
            "Return ONLY a valid JSON array matching the schema."
        )
        try:
            raw = await invoke_llm(
                [SystemMessage(content=system_prompt), HumanMessage(content=prompt)],
                tenant_id=tenant_id, user_id=user_id, request_type="supervisor_dependency_planning",
            )
        except Exception as exc:
            last_error = f"LLM call failed: {exc}"
            continue

        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = f"response was not valid JSON ({exc})"
            continue

        try:
            return _validate_dependency_plan(intents, pending_intents, parsed)
        except DependencyPlanValidationError as exc:
            last_error = str(exc)
            continue

    raise DependencyPlanningError(
        f"Failed to infer dependencies after {_MAX_DEPENDENCY_PLANNING_ATTEMPTS} attempts: {last_error}"
    )


# ---------------------------------------------------------------------
# Node 1: parse
# ---------------------------------------------------------------------

async def parse_node(state: SupervisorState) -> dict:
    """Resolves every @mention against real channel membership
    (services/channel_routing.py, unchanged) -- never a bare string match.
    An agent mentioned but not on the channel/project is reported in
    unresolved_mentions, not treated as a failure of the whole message
    (failure-semantics table: "don't fail the whole message")."""
    tenant_id, channel_id, message = state["tenant_id"], state["channel_id"], state["message"]
    mentions = parse_all_mentions(message)
    intents: list[dict] = []
    unresolved: list[dict] = []
    async with AsyncSessionLocal() as db:
        for name, text in mentions:
            if not text:
                # A mention with nothing after it (e.g. a trailing "@Nova"
                # with no instruction) carries no real work -- skip it
                # rather than dispatch an empty-goal task.
                continue
            agent = await resolve_mentioned_agent(db, channel_id, name)
            if agent is None:
                tenant_agent = await find_active_agent_in_tenant(db, tenant_id, name)
                if tenant_agent is None:
                    unresolved.append({
                        "name": name,
                        "reason": f"'{name}' doesn't match any agent in your workspace.",
                    })
                else:
                    unresolved.append({
                        "name": name,
                        "reason": f"{tenant_agent.name} exists but isn't a member of this channel/project yet.",
                    })
                continue
            intents.append({
                "agent_id": agent.id, "agent_name": agent.name, "text": text,
                "employee_type": agent.employee_type.value, "standing_instructions": agent.standing_instructions,
            })
    return {"intents": intents, "unresolved_mentions": unresolved}


# ---------------------------------------------------------------------
# Node 2: plan
# ---------------------------------------------------------------------

async def plan_node(state: SupervisorState) -> dict:
    """A deterministic fast path runs FIRST, for free: an exhaustive
    pairwise possessive-reference check (_references_agent_output) across
    every intent. Any edge it finds is applied at HIGH confidence with no
    LLM call at all. Only intents the fast path found nothing for, AND
    that still mention some other agent's name at all (a candidate for a
    paraphrased dependency -- _mentions_agent_name), go to the structured
    LLM planner (infer_dependencies), scoped to just that subset.

    Refuses to dispatch on any of three failure modes: exceeding the
    DAG-level task ceiling (checked BEFORE spending an LLM call), a
    circular dependency, or fan-in (a node needing more than one
    predecessor -- the schema can't store that; this can now come from
    the fast path alone, e.g. "combine Nova's and Ravi's numbers", or
    from the LLM). A low/medium-confidence proposed edge populates
    needs_clarification and blocks the WHOLE message (the LLM did answer,
    just without enough confidence to act on -- "ask once, cheap" was
    scoped to the whole message when this was designed, not to just the
    ambiguous pair). A planner OUTAGE is different: it means "the fast
    path already knows the truth for every intent it resolved; only the
    ones it couldn't judge are still unknown" -- those dispatch normally,
    and needs_clarification is raised only for the intents that actually
    needed (and didn't get) an LLM answer. blocked_intent_indices is what
    dispatch_node reads to tell these two needs_clarification shapes
    apart (all indices vs. a genuine subset)."""
    intents = state["intents"]

    if len(intents) > MAX_DAG_TASKS:
        return {
            "error": (
                f"This message would dispatch {len(intents)} tasks, over the "
                f"{MAX_DAG_TASKS}-task ceiling for one message. Split it into smaller messages."
            ),
            "error_kind": "ceiling",
            "edges": [], "inferred_edge_notices": [], "needs_clarification": None,
            "blocked_intent_indices": [],
        }

    if len(intents) <= 1:
        # Nothing to order -- asking about a single agent is meaningless,
        # and skipping the fast path/LLM entirely avoids any cost on a
        # message that could never have produced an ask or an edge.
        return {
            "edges": [], "inferred_edge_notices": [], "error": None, "error_kind": None,
            "needs_clarification": None, "blocked_intent_indices": [],
        }

    n = len(intents)
    plan: list[dict] = [
        {"agent": intent["agent_name"], "depends_on": [], "confidence": None, "reason": None}
        for intent in intents
    ]

    # Fast path: exhaustive pairwise possessive check. Every match is a
    # HIGH-confidence edge, free.
    for i, intent in enumerate(intents):
        for j, other in enumerate(intents):
            if i == j:
                continue
            if _references_agent_output(intent["text"], other["agent_name"]):
                plan[i]["depends_on"].append(other["agent_name"])
                plan[i]["confidence"] = "high"
                plan[i]["reason"] = f"explicit reference to {other['agent_name']}'s output"

    # Only an intent the fast path left empty, and that still mentions
    # another agent by name at all, is worth an LLM call -- see
    # _mentions_agent_name's own docstring for why a silent intent needs
    # no call to conclude "no dependency."
    pending_indices = [
        i for i, intent in enumerate(intents)
        if not plan[i]["depends_on"]
        and any(
            _mentions_agent_name(intent["text"], other["agent_name"])
            for j, other in enumerate(intents) if j != i
        )
    ]

    needs_clarification: list[dict] | None = None
    blocked_indices: set[int] = set()

    if pending_indices:
        pending_intents = [intents[i] for i in pending_indices]
        try:
            llm_plan = await infer_dependencies(
                tenant_id=state["tenant_id"], user_id=state["user_id"], message=state["message"],
                intents=intents, pending_intents=pending_intents,
            )
        except DependencyPlanningError as exc:
            log.warning("supervisor.dependency_planning_failed", error=str(exc))
            # A total planner outage must never discard edges the fast
            # path already found: "regex-only behaviour plus a
            # clarification prompt for the rest." Every intent the fast
            # path resolved (an edge, or conclusively no edge at all)
            # dispatches normally; only the intents that genuinely needed
            # the LLM, and didn't get an answer, are withheld.
            blocked_indices = set(pending_indices)
            agent_names = [intents[i]["agent_name"] for i in pending_indices]
            needs_clarification = [{
                "agents": agent_names,
                "question": (
                    f"I couldn't confidently determine what order {', '.join(agent_names)} should "
                    "run in relative to the rest of this message. Should they run independently, "
                    "or is there a specific order?"
                ),
                "options": ["Run independently"],
                "reason": f"The dependency planner failed: {exc}",
            }]
        else:
            by_name = {p["agent"]: p for p in llm_plan}
            for i in pending_indices:
                plan[i] = by_name[intents[i]["agent_name"]]

    name_to_index = {intent["agent_name"]: idx for idx, intent in enumerate(intents)}

    # Fan-in: this schema stores a single predecessor per task. Refuse
    # outright rather than silently drop an edge or linearize an order
    # nobody asked for -- regardless of whether the offending entry came
    # from the fast path or the LLM.
    fan_in = [p for p in plan if len(p["depends_on"]) > 1]
    if fan_in:
        names = ", ".join(p["agent"] for p in fan_in)
        return {
            "error": (
                f"{names} would need more than one predecessor, but this schema stores a single "
                "dependency per task. Refusing to dispatch -- split this into separate messages, "
                "or say explicitly which single dependency each agent should wait on."
            ),
            "error_kind": "fan_in",
            "edges": [], "inferred_edge_notices": [], "needs_clarification": None,
            "blocked_intent_indices": [],
        }

    edges: list[tuple[int, int]] = []
    notices: list[str] = []
    asks: list[dict] = []
    for i, p in enumerate(plan):
        if i in blocked_indices:
            continue  # already asking about this one (planner outage) -- don't also apply or ask again
        if not p["depends_on"]:
            continue
        dep_name = p["depends_on"][0]
        if p["confidence"] == "high":
            edges.append((name_to_index[dep_name], i))
            reason_clause = f" -- {p['reason']}" if p.get("reason") else ""
            notices.append(f"Running {p['agent']}'s task after {dep_name}'s{reason_clause}.")
        else:
            # medium or low confidence: the LLM DID answer here, just
            # without enough confidence to act on -- asking once is
            # cheap, a confident wrong answer is not. Unlike a planner
            # OUTAGE (handled above), this blocks the whole message, not
            # just this pair -- see this function's own docstring.
            asks.append({
                "agents": [dep_name, p["agent"]],
                "question": f"Should {p['agent']}'s task wait for {dep_name}, or run independently?",
                "options": [f"Wait for {dep_name}", "Run independently"],
                "reason": p.get("reason") or f"Possible dependency detected ({p['confidence']} confidence).",
            })

    if asks:
        return {
            "error": None, "edges": [], "inferred_edge_notices": [], "needs_clarification": asks,
            "blocked_intent_indices": list(range(n)),
        }

    # Cycle detection (Kahn's algorithm) over the applied edges -- fast
    # path and LLM edges together.
    indegree = [0] * n
    adj: dict[int, list[int]] = {k: [] for k in range(n)}
    for (a, b) in edges:
        adj[a].append(b)
        indegree[b] += 1
    frontier = [k for k in range(n) if indegree[k] == 0]
    visited = 0
    while frontier:
        node = frontier.pop()
        visited += 1
        for nxt in adj[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                frontier.append(nxt)

    if visited != n:
        involved = sorted({intents[k]["agent_name"] for k in range(n) if indegree[k] > 0})
        return {
            "error": (
                f"Circular dependency inferred among: {', '.join(involved)}. "
                "Refusing to dispatch -- reorder the request so no agent's input depends on a later agent's output."
            ),
            "error_kind": "cycle",
            "edges": [], "inferred_edge_notices": [], "needs_clarification": None,
            "blocked_intent_indices": [],
        }

    return {
        "edges": edges, "inferred_edge_notices": notices, "error": None, "error_kind": None,
        "needs_clarification": needs_clarification, "blocked_intent_indices": sorted(blocked_indices),
    }


# ---------------------------------------------------------------------
# Node 3: dispatch
# ---------------------------------------------------------------------

async def dispatch_node(state: SupervisorState) -> dict:
    """One Task row per DISPATCHABLE intent, reusing the existing
    tasks/task_steps lifecycle (models/all_models.py) -- not a parallel
    one. status starts at SUPERVISOR_QUEUED regardless of whether the
    task has an unmet dependency; readiness is computed at run time
    (_find_ready_task_ids), not stored as a separate status.

    blocked_intent_indices distinguishes two needs_clarification shapes:
    a confidence-based ask blocks EVERY intent (plan_node sets it to
    range(n)); a planner-outage ask blocks only the specific intents that
    needed (and didn't get) an LLM answer, so everything else -- fast-
    path edges and conclusively-independent intents alike -- dispatches
    here exactly as if nothing had failed. An intent whose OWN dependency
    is fine but whose dependency TARGET is blocked is transitively
    blocked too, rather than get a depends_on_task_id pointing at a Task
    row that will never exist."""
    if state.get("error"):
        return {}

    intents = state["intents"]
    n = len(intents)
    blocked = set(state.get("blocked_intent_indices") or [])
    if blocked and len(blocked) == n:
        return {}  # fully blocked -- nothing to dispatch

    depends_on_idx = {b: a for (a, b) in state["edges"]}  # single predecessor per node

    changed = True
    while changed:
        changed = False
        for i in range(n):
            if i in blocked:
                continue
            dep = depends_on_idx.get(i)
            if dep is not None and dep in blocked:
                blocked.add(i)
                changed = True

    dispatch_indices = [i for i in range(n) if i not in blocked]
    if not dispatch_indices:
        return {"tasks": []}

    tasks: list[dict] = []
    async with AsyncSessionLocal() as db:
        task_rows: dict[int, Task] = {}
        for i in dispatch_indices:
            intent = intents[i]
            task = Task(
                tenant_id=state["tenant_id"], user_id=state["user_id"], agent_id=intent["agent_id"],
                originating_session_id=state["channel_id"], goal=intent["text"],
                task_shape=TaskShape.SUPERVISOR_INTENT, status=TaskStatus.SUPERVISOR_QUEUED,
                step_budget_max=SUPERVISOR_TASK_STEP_BUDGET,
            )
            db.add(task)
            task_rows[i] = task
        await db.flush()  # real ids, before wiring dependencies/steps

        for i in dispatch_indices:
            dep_i = depends_on_idx.get(i)
            if dep_i is not None:  # guaranteed to also be in dispatch_indices, by the propagation above
                task_rows[i].depends_on_task_id = task_rows[dep_i].id
            db.add(TaskStep(
                task_id=task_rows[i].id, tenant_id=task_rows[i].tenant_id, step_index=0,
                description=intents[i]["text"],
                source=TaskStepSource.SUPERVISOR_DISPATCHED, status=TaskStepStatus.PENDING,
            ))
        await db.commit()

        tasks = [
            {
                "intent_index": i, "task_id": task_rows[i].id,
                "agent_id": intents[i]["agent_id"], "agent_name": intents[i]["agent_name"],
            }
            for i in dispatch_indices
        ]

    # Shape B ack, the moment dispatch happens -- before run_node has
    # started a single one of these, let alone finished it. Every
    # dispatched task starts life SUPERVISOR_QUEUED (readiness is computed
    # separately, at run time), so "queued" is always true here regardless
    # of whether this particular task turns out ready in the very next
    # wave.
    sink = state.get("event_sink")
    for t in tasks:
        await _emit(sink, "supervisor_task", {
            "task_id": t["task_id"], "agent_id": t["agent_id"], "agent_name": t["agent_name"],
            "status": "queued", "response": None, "message_id": None,
        })

    return {"tasks": tasks}


# ---------------------------------------------------------------------
# Shared scheduling core -- used by BOTH the run/handoff nodes below AND
# retry_task() (the "retrying A releases B" behavior happens well after
# the initial graph invocation has already returned, so it re-enters this
# same DB-state-driven core directly rather than re-invoking the graph).
# ---------------------------------------------------------------------

async def _find_ready_task_ids(db, channel_id: str) -> list[str]:
    """A SUPERVISOR_QUEUED task in this channel is "ready" if it has no
    dependency, or its dependency has reached COMPLETED. Deliberately
    re-derived from DB state on every call rather than cached in memory --
    this is what makes retry_task() safe to call independently of the
    original graph invocation."""
    r = await db.execute(select(Task).where(
        Task.originating_session_id == channel_id, Task.status == TaskStatus.SUPERVISOR_QUEUED,
    ))
    candidates = r.scalars().all()
    ready = []
    for t in candidates:
        if t.depends_on_task_id is None:
            ready.append(t.id)
            continue
        dep = await db.get(Task, t.depends_on_task_id)
        if dep is not None and dep.status == TaskStatus.COMPLETED:
            ready.append(t.id)
    return ready


def _summarize_approved_action(action_name: str, execution_result: dict | None) -> str:
    """The outcome_summary text for a supervisor task that completes via
    a human's approval rather than a normal agent turn -- there is no
    natural-language AIMessage to fall back on here (the turn that
    requested this action ended the moment it got blocked), so this is
    the most honest summary available: what was approved, and what the
    tool itself actually returned."""
    if not execution_result:
        return f"Approved and executed `{action_name}`."
    if "error" in execution_result:
        return f"Approved `{action_name}`, but execution failed: {execution_result['error']}"
    return f"Approved and executed `{action_name}`.\n\nResult: {execution_result}"


async def _persist_task_completion_message(
    db, *, tenant_id: str, channel_id: str, user_id: str, agent_id: str, content: str,
) -> str:
    """One ChatMessage per supervisor task that actually completes -- the
    single place this happens, regardless of which of the three callers
    (the initial run_node wave, retry_task()'s wave, or
    resolve_task_approval()'s release) got the task there. Previously this
    lived in api/v1/chat.py, reading back result["tasks"] once
    run_supervisor() itself had already returned in full -- which worked
    for the initial dispatch, but silently did nothing for a task that
    finishes later from a *different* HTTP request (a retry, or a human's
    approval click): nobody was there afterward to read `result["tasks"]`
    and persist a response. Moving it here means "a supervisor task
    completed" and "its answer is in the transcript" can never drift
    apart, no matter which of the three paths got it there.

    personality_mode/operation_mode are deliberately left unset (None,
    both nullable columns) rather than reusing the human's own chat-level
    preference -- that setting describes the human's tone preference for
    the whole channel, not the tone the dispatched agent's own identity
    (agent/personality.py's EMPLOYEE_TYPE_IDENTITY) actually used."""
    message_id = str(uuid.uuid4())
    db.add(ChatMessage(
        id=message_id, tenant_id=tenant_id, user_id=user_id, session_id=channel_id,
        role="assistant", content=content, agent_id=agent_id, mentioned_agent_id=None,
        tool_calls=[], created_at=datetime.utcnow(),
    ))
    return message_id


async def _run_one_task(
    task_id: str, *, tenant_id: str, channel_id: str, user_id: str, caller_role: str,
    event_sink: EventSink = None,
) -> dict:
    """Runs exactly one ready supervisor task: loads it and its single
    TaskStep, invokes run_agent_stream() (agent/dataops_agent.py) --
    the same generator POST /api/v1/chat/stream's own single-agent path
    consumes -- and persists whichever of the three real outcomes
    resulted. Approval and failure are not treated the same: a paused-
    for-approval task is not a failure (its dependents keep waiting
    normally, never BLOCKED_ON_DEPENDENCY), matching the failure-
    semantics table's own distinction ("A needs approval -> B holds" vs
    "A fails -> B blocked").

    event_sink, when given, receives this task's own token/tool_start/
    tool_end events live, each tagged with task_id/agent_id so a caller
    juggling several of these concurrently (asyncio.gather in
    _run_ready_wave below) can route every event to the right place --
    interleaved events from parallel tasks are the expected shape, not
    something to serialize away. A caller with no live listener (retry_task(),
    resolve_task_approval()) simply passes none."""
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        step = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().first()
        task.status = TaskStatus.SUPERVISOR_RUNNING
        task.started_at = datetime.utcnow()
        step.status = TaskStepStatus.RUNNING
        step.started_at = datetime.utcnow()
        goal, agent_id = task.goal, task.agent_id
        agent = await db.get(AgentInstance, agent_id)
        agent_name = agent.name if agent is not None else agent_id
        await db.commit()

    await _emit(event_sink, "supervisor_task", {
        "task_id": task_id, "agent_id": agent_id, "agent_name": agent_name,
        "status": "running", "response": None, "message_id": None,
    })

    final_state = None
    try:
        async for ev in run_agent_stream(
            user_message=goal, tenant_id=tenant_id, user_id=user_id, session_id=channel_id,
            caller_role=caller_role, agent_id=agent_id,
        ):
            if ev["type"] == "token":
                await _emit(event_sink, "token", {"task_id": task_id, "agent_id": agent_id, "delta": ev["delta"]})
            elif ev["type"] == "tool_start":
                await _emit(event_sink, "tool_start", {
                    "task_id": task_id, "agent_id": agent_id,
                    "name": ev["name"], "args_summary": ev["args_summary"],
                })
            elif ev["type"] == "tool_end":
                await _emit(event_sink, "tool_end", {
                    "task_id": task_id, "agent_id": agent_id,
                    "name": ev["name"], "result_summary": ev["result_summary"], "ok": ev["ok"],
                })
            elif ev["type"] == "final_state":
                final_state = ev["state"]
    except Exception as exc:
        log.warning("supervisor.task_run_failed", task_id=task_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            step = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().first()
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.termination_reason = str(exc)
            step.status = TaskStepStatus.FAILED
            step.completed_at = datetime.utcnow()
            step.error_message = str(exc)
            await db.commit()
        await _emit(event_sink, "supervisor_task", {
            "task_id": task_id, "agent_id": agent_id, "agent_name": agent_name,
            "status": "failed", "response": None, "message_id": None,
        })
        return {"task_id": task_id, "status": "failed", "error": str(exc)}

    # The graph never reached its final state without itself raising --
    # not expected, but _run_agent_and_persist_stream treats the same
    # situation as a real (if mild) failure rather than assuming success,
    # and this mirrors that rather than inventing a third behavior.
    result = (
        _finalize_agent_result(final_state, channel_id, tenant_id, user_id) if final_state is not None
        else {"response": "AXIOM hit an error before finishing this response.", "pending_approvals": []}
    )

    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        step = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().first()

        if result.get("pending_approvals"):
            task.status = TaskStatus.PAUSED_NEEDS_APPROVAL
            step.status = TaskStepStatus.BLOCKED_APPROVAL
            # Only the first blocked call gets linked to this step -- a
            # SUPERVISOR_INTENT task has exactly one step by construction
            # (SUPERVISOR_TASK_STEP_BUDGET), the same single-approval-per-
            # step assumption task_executor.py's own structured-plan flow
            # already makes for TaskStep.approval_request_id.
            for i, pa in enumerate(result["pending_approvals"]):
                approval = ApprovalRequest(
                    tenant_id=tenant_id, user_id=user_id, session_id=channel_id,
                    action_name=pa["name"], action_args=pa.get("args", {}),
                    risk_level=pa.get("risk_level", "high"), reason=pa.get("reason", ""),
                )
                db.add(approval)
                if i == 0:
                    await db.flush()  # real id, before linking
                    step.approval_request_id = approval.id
            await db.commit()
            await _emit(event_sink, "supervisor_task", {
                "task_id": task_id, "agent_id": agent_id, "agent_name": agent_name,
                "status": "paused_needs_approval", "response": None, "message_id": None,
            })
            return {"task_id": task_id, "status": "paused_needs_approval"}

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        step.status = TaskStepStatus.SUCCEEDED
        step.completed_at = datetime.utcnow()
        step.outcome_summary = result["response"]
        message_id = await _persist_task_completion_message(
            db, tenant_id=tenant_id, channel_id=channel_id, user_id=user_id,
            agent_id=agent_id, content=result["response"],
        )
        await db.commit()

    await _emit(event_sink, "supervisor_task", {
        "task_id": task_id, "agent_id": agent_id, "agent_name": agent_name,
        "status": "completed", "response": result["response"], "message_id": message_id,
    })
    return {"task_id": task_id, "status": "completed", "response": result["response"]}


async def _block_dependents(db, failed_task_id: str, *, reason: str | None = None) -> list[str]:
    """Failure-semantics table: "A fails, B depends on it -> B moves to
    blocked, not failed. The thread says which upstream task broke."
    termination_reason (an existing Task column) carries that naming --
    the same field a wall-clock/loop-cap stop already uses for a non-clean
    reason with no single step to blame.

    `reason` defaults to the original "which failed" wording (every
    existing caller -- _run_ready_wave, on a real task-run failure) but a
    REJECTED approval is a human decision, not a failure, and must say so
    plainly rather than reuse language that implies something broke on
    its own -- see resolve_task_approval's own rejected branch."""
    r = await db.execute(select(Task).where(
        Task.depends_on_task_id == failed_task_id, Task.status == TaskStatus.SUPERVISOR_QUEUED,
    ))
    dependents = r.scalars().all()
    blocked_ids = []
    for dep in dependents:
        dep.status = TaskStatus.BLOCKED_ON_DEPENDENCY
        dep.termination_reason = reason or f"Blocked: waiting on task {failed_task_id}, which failed."
        blocked_ids.append(dep.id)
    if dependents:
        await db.commit()
    return blocked_ids


async def _write_handoffs_for_completion(
    db, completed_task: Task, *, tenant_id: str, channel_id: str, project_id: str | None,
) -> list[str]:
    """"On completion, writes a Handoff row... and releases dependents."
    Also injects the completed task's real output text into each
    dependent's own goal -- the acceptance test's literal requirement
    ("B's input contains A's output") needs the actual text present when
    the dependent later runs through run_agent(), not just a Handoff row
    existing as a side record. Dependents were already SUPERVISOR_QUEUED
    (never blocked by a mere in-progress predecessor) -- "release" here
    means _find_ready_task_ids will now see them as ready, not a status
    change on the dependent itself.

    Integration Phase 4 item 2: agent A's output_text used to be
    concatenated into agent B's goal completely unwrapped, as trusted
    text -- exactly the gap Phase 1 flagged. output_text can carry
    anything the underlying tool/source produced (E1's own finding: a
    poisoned column name reaching generate_sql() via nothing more than an
    ordinary profiled schema), and until this fix nothing stood between
    that and agent B's own prompt. Two passes now run before it goes
    anywhere, same mechanisms Item #6/#10 already established, not
    reinvented:
      - pii_classifier.redact_free_text() masks PII-shaped substrings
        (reusing VALUE_DETECTORS, not a second pattern set) -- its
        findings populate Handoff.withheld for real, instead of the
        permanent [] the field was hardcoded to before.
      - prompt_guard.wrap("tool_result", ...) marks the (already PII-
        redacted) text as untrusted data the same way any other tool
        result is marked before it reaches a prompt -- agent B's own
        system prompt already tells it text in a <tool_result> tag is
        data, never an instruction, regardless of what it claims.
    from_agent_name also goes through prompt_guard.sanitize_identifier()
    -- the plain "[Handoff from X]" framing was itself the exact
    bracket-authority shape Item #6's A4 finding showed the model had
    been taught to trust; replaced with unbracketed prose plus the
    recognised tag."""
    r = await db.execute(select(Task).where(
        Task.depends_on_task_id == completed_task.id, Task.status == TaskStatus.SUPERVISOR_QUEUED,
    ))
    dependents = r.scalars().all()
    if not dependents:
        return []

    from_step = (await db.execute(select(TaskStep).where(TaskStep.task_id == completed_task.id))).scalars().first()
    from_agent = await db.get(AgentInstance, completed_task.agent_id)
    raw_output_text = from_step.outcome_summary or ""
    output_text, pii_withheld = pii_classifier.redact_free_text(raw_output_text)
    wrapped_output = prompt_guard.wrap("tool_result", output_text)
    summary_source = prompt_guard.neutralize_markup(output_text)
    summary = summary_source if len(summary_source) <= 200 else summary_source[:200].rstrip() + "…"
    from_agent_name = prompt_guard.sanitize_identifier(
        from_agent.name if from_agent is not None else completed_task.agent_id
    )

    handoff_ids = []
    for dep in dependents:
        handoff = Handoff(
            tenant_id=tenant_id, channel_id=channel_id, project_id=project_id,
            from_agent_id=completed_task.agent_id, to_agent_id=dep.agent_id,
            from_task_id=completed_task.id, to_task_id=dep.id,
            payload_summary=summary, payload_ref=from_step.id, withheld=pii_withheld,
        )
        db.add(handoff)
        await db.flush()
        handoff_ids.append(handoff.id)
        dep.goal = dep.goal + f"\n\nHandoff from {from_agent_name}:\n{wrapped_output}"
    await db.commit()
    return handoff_ids


async def _run_ready_wave(
    ready_ids: list[str], *, tenant_id: str, channel_id: str, user_id: str, caller_role: str,
    event_sink: EventSink = None,
) -> tuple[list[str], list[str]]:
    """Runs every ready task in this wave IN PARALLEL ("run: ... Parallel
    where the DAG allows") and blocks any dependents of a task that failed
    in this same wave. Returns (completed_task_ids, failed_task_ids).

    asyncio.gather runs every _run_one_task() call concurrently, so their
    event_sink calls naturally interleave at each other's await points --
    exactly the "parallel tasks stream concurrently, interleaved events
    are expected" requirement, with no extra coordination needed here:
    asyncio.Queue.put (api/v1/chat.py's sink) is already safe to call
    from multiple coroutines at once."""
    results = await asyncio.gather(*[
        _run_one_task(
            tid, tenant_id=tenant_id, channel_id=channel_id, user_id=user_id,
            caller_role=caller_role, event_sink=event_sink,
        )
        for tid in ready_ids
    ])
    completed = [r["task_id"] for r in results if r["status"] == "completed"]
    failed = [r["task_id"] for r in results if r["status"] == "failed"]
    if failed:
        async with AsyncSessionLocal() as db:
            for fid in failed:
                await _block_dependents(db, fid)
    return completed, failed


# ---------------------------------------------------------------------
# Node 4: run / Node 5: handoff
# ---------------------------------------------------------------------

async def run_node(state: SupervisorState) -> dict:
    if state.get("error"):
        return {}
    async with AsyncSessionLocal() as db:
        ready_ids = await _find_ready_task_ids(db, state["channel_id"])
    if not ready_ids:
        return {"completed_this_wave": []}
    completed, _failed = await _run_ready_wave(
        ready_ids, tenant_id=state["tenant_id"], channel_id=state["channel_id"],
        user_id=state["user_id"], caller_role=state["caller_role"], event_sink=state.get("event_sink"),
    )
    return {"completed_this_wave": completed}


async def handoff_node(state: SupervisorState) -> dict:
    if state.get("error") or not state.get("completed_this_wave"):
        return {"more_ready": False}
    new_handoff_ids: list[str] = []
    async with AsyncSessionLocal() as db:
        for tid in state["completed_this_wave"]:
            task = await db.get(Task, tid)
            new_handoff_ids.extend(await _write_handoffs_for_completion(
                db, task, tenant_id=state["tenant_id"], channel_id=state["channel_id"],
                project_id=state["project_id"],
            ))
        more_ready = await _find_ready_task_ids(db, state["channel_id"])
    return {
        "handoffs_created": state.get("handoffs_created", []) + new_handoff_ids,
        "more_ready": bool(more_ready),
    }


def _route_after_plan(state: SupervisorState) -> str:
    if state.get("error"):
        return "end"
    intents = state.get("intents") or []
    blocked = state.get("blocked_intent_indices") or []
    if intents and len(blocked) == len(intents):
        return "end"  # every intent blocked -- nothing for dispatch to do
    return "dispatch"


def _route_after_handoff(state: SupervisorState) -> str:
    return "run" if state.get("more_ready") else "end"


# ---------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------

def build_supervisor_graph():
    from langgraph.graph import StateGraph, END

    graph = StateGraph(SupervisorState)
    graph.add_node("parse", parse_node)
    graph.add_node("plan", plan_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("run", run_node)
    graph.add_node("handoff", handoff_node)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "plan")
    graph.add_conditional_edges("plan", _route_after_plan, {"dispatch": "dispatch", "end": END})
    graph.add_edge("dispatch", "run")
    graph.add_edge("run", "handoff")
    graph.add_conditional_edges("handoff", _route_after_handoff, {"run": "run", "end": END})
    return graph.compile()


_SUPERVISOR_GRAPH = None


def get_supervisor_graph():
    global _SUPERVISOR_GRAPH
    if _SUPERVISOR_GRAPH is None:
        _SUPERVISOR_GRAPH = build_supervisor_graph()
    return _SUPERVISOR_GRAPH


async def run_supervisor(
    *, tenant_id: str, channel_id: str, project_id: str | None, user_id: str, caller_role: str, message: str,
    event_sink: EventSink = None,
) -> dict:
    """Entry point. event_sink, when given, receives every live
    supervisor_task/token/tool_start/tool_end event as this call's waves
    actually run (see dispatch_node/_run_one_task) -- api/v1/chat.py's
    streaming route is the only real caller that passes one; every other
    caller (tests, retry_task(), resolve_task_approval()) gets the
    original headless behavior for free via the default.

    Wrapped in async_tenant_context(tenant_id) (Integration Phase 3 fix,
    2026-09-23): every node this compiled graph runs (dispatch_node,
    run_node/_run_one_task, handoff writing) opens its own bare
    AsyncSessionLocal() with no tenant scope of its own -- this module's
    own header docstring says it was "headless only... every entry point
    meant to be called directly, the way tests/test_supervisor.py does"
    (its tests establish tenant context themselves before calling in).
    That stopped being true the moment api/v1/chat.py wired this into a
    live HTTP route, and nothing was added here to cover the gap: proven
    live, every dispatch failed with "new row violates row-level security
    policy for table task_steps" -- current_tenant_id was '' inside
    dispatch_node's own AsyncSessionLocal(), for every tenant, every time,
    not just under concurrent load. Fails closed (RLS correctly refused
    the wrong-tenant write), not a leak -- but a 100%-reproducible outage
    for every multi-agent dispatch before this fix."""
    async with async_tenant_context(tenant_id):
        graph = get_supervisor_graph()
        return await graph.ainvoke({
            "tenant_id": tenant_id, "channel_id": channel_id, "project_id": project_id,
            "user_id": user_id, "caller_role": caller_role, "message": message,
            "intents": [], "unresolved_mentions": [], "edges": [], "inferred_edge_notices": [],
            "error": None, "error_kind": None, "needs_clarification": None, "blocked_intent_indices": [],
            "tasks": [], "completed_this_wave": [],
            "handoffs_created": [], "more_ready": False, "event_sink": event_sink,
        })


async def _drain_ready_waves(
    channel_id: str, *, tenant_id: str, project_id: str | None, user_id: str, caller_role: str,
    event_sink: EventSink = None,
) -> dict:
    """The actual wave-scheduling core shared by retry_task() and
    resolve_task_approval() below -- run_node/handoff_node's own "find
    what's ready, run it, write its handoffs, repeat until nothing's
    ready" loop, extracted so both callers reuse the identical mechanism
    rather than each re-deriving their own. Neither caller re-invokes the
    graph (see retry_task()'s own docstring on why: LangGraph
    checkpointing isn't wired up here, and both calls happen well after
    the original run_supervisor() invocation already returned).

    Wrapped in async_tenant_context(tenant_id) for the same reason
    run_supervisor() is -- the bare AsyncSessionLocal() calls below and
    inside _run_ready_wave()/_run_one_task()/_write_handoffs_for_completion()
    have no tenant scope of their own (Integration Phase 3 fix,
    2026-09-23)."""
    completed: list[str] = []
    handoffs_created: list[str] = []
    async with async_tenant_context(tenant_id):
        while True:
            async with AsyncSessionLocal() as db:
                ready_ids = await _find_ready_task_ids(db, channel_id)
            if not ready_ids:
                break
            newly_completed, _failed = await _run_ready_wave(
                ready_ids, tenant_id=tenant_id, channel_id=channel_id, user_id=user_id,
                caller_role=caller_role, event_sink=event_sink,
            )
            completed.extend(newly_completed)
            async with AsyncSessionLocal() as db:
                for cid in newly_completed:
                    task_row = await db.get(Task, cid)
                    handoffs_created.extend(await _write_handoffs_for_completion(
                        db, task_row, tenant_id=tenant_id, channel_id=channel_id, project_id=project_id,
                    ))
    return {"completed": completed, "handoffs_created": handoffs_created}


async def retry_task(
    task_id: str, *, tenant_id: str, channel_id: str, project_id: str | None, user_id: str, caller_role: str,
) -> dict:
    """"Retrying A releases B" (failure-semantics table). Resets the
    failed task and any direct dependent currently BLOCKED_ON_DEPENDENCY,
    then re-enters _drain_ready_waves (the same wave-scheduling core
    run_node/handoff_node use) -- not a second, parallel retry mechanism
    -- until nothing more is ready."""
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.status != TaskStatus.FAILED:
            raise ValueError(
                f"Task {task_id} is not a failed supervisor task "
                f"(status={task.status.value if task else 'missing'})."
            )
        task.status = TaskStatus.SUPERVISOR_QUEUED
        task.termination_reason = None
        task.completed_at = None
        step = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().first()
        step.status = TaskStepStatus.PENDING
        step.error_message = None
        step.started_at = None
        step.completed_at = None

        r = await db.execute(select(Task).where(
            Task.depends_on_task_id == task_id, Task.status == TaskStatus.BLOCKED_ON_DEPENDENCY,
        ))
        released_ids = []
        for dep in r.scalars().all():
            dep.status = TaskStatus.SUPERVISOR_QUEUED
            dep.termination_reason = None
            released_ids.append(dep.id)
        await db.commit()

    drained = await _drain_ready_waves(
        channel_id, tenant_id=tenant_id, project_id=project_id, user_id=user_id, caller_role=caller_role,
    )
    return {"released_from_block": released_ids, **drained}


# ---------------------------------------------------------------------
# Approval release -- the other way a paused supervisor task resumes.
# PAUSED_NEEDS_APPROVAL is not a failure (see _run_one_task's own
# docstring), so a dependent waiting on one was never blocked in the
# first place; it's still sitting SUPERVISOR_QUEUED the whole time. What
# was actually missing: nothing ever told the paused Task itself "you're
# done now" once a human resolved its ApprovalRequest, so
# _find_ready_task_ids never saw its dependent as ready either. These two
# functions are that missing link -- called from
# modules/governance/policy_engine.py (approve()/reject()), which stays
# domain-agnostic and only knows "an approval resolved"; everything about
# what a supervisor Task/dependent/handoff actually IS lives here.
# ---------------------------------------------------------------------

async def find_supervisor_task_for_approval(approval_id: str) -> str | None:
    """Looks up whether `approval_id` is blocking a supervisor-dispatched
    task, via the same TaskStep.approval_request_id link task_executor.py's
    own structured-plan approval flow already uses -- not a second,
    parallel linkage. Filtered to TaskShape.SUPERVISOR_INTENT specifically:
    a structured task's step carries this same link, and must not be
    accidentally routed through supervisor-only resolution logic below."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(TaskStep.task_id).join(Task, Task.id == TaskStep.task_id).where(
                TaskStep.approval_request_id == approval_id, Task.task_shape == TaskShape.SUPERVISOR_INTENT,
            )
        )
        row = r.first()
        return row[0] if row else None


async def describe_unblocked_dependents(task_id: str) -> str | None:
    """§7.3.E: "Where a dependent task is held behind this one, the card
    must say so." Returns the human sentence, or None when nothing is
    waiting on this task -- policy_engine.py's _serialize() folds this
    straight into the approval dict it already builds, no new shape."""
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(
            Task.depends_on_task_id == task_id, Task.status == TaskStatus.SUPERVISOR_QUEUED,
        ))
        dependents = r.scalars().all()
        if not dependents:
            return None
        names = []
        for dep in dependents:
            agent = await db.get(AgentInstance, dep.agent_id)
            names.append(agent.name if agent is not None else dep.agent_id)
    if len(names) == 1:
        return f"Approving this also unblocks {names[0]}'s task."
    return f"Approving this also unblocks {', '.join(names[:-1])} and {names[-1]}'s tasks."


async def resolve_task_approval(task_id: str, approval_id: str, *, approved: bool) -> dict:
    """The task-aware half of resolving an ApprovalRequest that turns out
    to belong to a supervisor task (see find_supervisor_task_for_approval).

    Approved and the tool executed cleanly: the task COMPLETES for real
    (its step gets the actual execution_result as outcome_summary, a
    ChatMessage is persisted the same way any other completed supervisor
    task's answer is -- _persist_task_completion_message, not a second
    persistence path), and its dependents are released through
    _drain_ready_waves -- retry_task()'s own core, reused rather than
    reinvented.

    Rejected outright, OR approved but the tool itself errored on
    execution: this task did NOT produce a usable result, so its
    dependents move to BLOCKED_ON_DEPENDENCY exactly the way any other
    task failure blocks them (_block_dependents) -- a rejection is a
    decision, not a pause, and must not leave a dependent sitting
    SUPERVISOR_QUEUED forever with no explanation.

    caller_role for any dependent that this releases is re-read fresh
    from the task's own initiating user (mirrors task_executor.py's
    _caller_still_authorized() -- never trust a role passed in from
    further up the call stack, always re-derive it from the DB at the
    point of use)."""
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.status != TaskStatus.PAUSED_NEEDS_APPROVAL:
            return {"outcome": "not_resumable", "status": task.status.value if task else "missing"}
        step = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().first()
        approval = await db.get(ApprovalRequest, approval_id)
        tenant_id, channel_id, user_id, agent_id = (
            task.tenant_id, task.originating_session_id, task.user_id, task.agent_id,
        )
        action_name = approval.action_name if approval is not None else "unknown_action"
        execution_result = approval.execution_result if approval is not None else None

        user_row = await db.get(User, user_id)
        caller_role = user_row.role if user_row is not None else "member"

        execution_failed = isinstance(execution_result, dict) and "error" in execution_result
        succeeded = approved and not execution_failed

        if not succeeded:
            reason = (
                f"Blocked: waiting on task {task_id}, which was rejected."
                if not approved else
                f"Blocked: waiting on task {task_id}, which failed on execution: "
                f"{execution_result.get('error') if execution_result else 'unknown error'}."
            )
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.termination_reason = "Approval rejected." if not approved else reason
            step.status = TaskStepStatus.FAILED
            step.completed_at = datetime.utcnow()
            step.error_message = task.termination_reason
            await db.commit()
            blocked_ids = await _block_dependents(db, task_id, reason=reason)
            return {
                "outcome": "rejected" if not approved else "approved_but_failed",
                "blocked_dependents": blocked_ids,
            }

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        step.status = TaskStepStatus.SUCCEEDED
        step.completed_at = datetime.utcnow()
        step.outcome_summary = _summarize_approved_action(action_name, execution_result)
        step.raw_result = execution_result
        await _persist_task_completion_message(
            db, tenant_id=tenant_id, channel_id=channel_id, user_id=user_id,
            agent_id=agent_id, content=step.outcome_summary,
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        project_id = (
            await db.execute(select(Channel.project_id).where(Channel.id == channel_id))
        ).scalar_one_or_none()
        task_row = await db.get(Task, task_id)
        handoffs_created = await _write_handoffs_for_completion(
            db, task_row, tenant_id=tenant_id, channel_id=channel_id, project_id=project_id,
        )

    drained = await _drain_ready_waves(
        channel_id, tenant_id=tenant_id, project_id=project_id, user_id=user_id, caller_role=caller_role,
    )
    return {
        "outcome": "approved_and_completed",
        "completed": [task_id] + drained["completed"],
        "handoffs_created": handoffs_created + drained["handoffs_created"],
    }
