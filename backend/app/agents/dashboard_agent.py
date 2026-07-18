"""Dashboard worker — read the living PDP + **propose** changes via native tools (P8-03, §5.2).

The request-path worker behind :attr:`~app.agents.state.WorkerName.DASHBOARD`. Mirrors the
market / RAG workers' factory-and-closure shape (:func:`make_market_node` /
:func:`make_rag_node`): :func:`make_dashboard_node` binds its collaborators (the shared
:class:`~app.services.dashboard.DashboardService` + the same :class:`LLMCompleter` router the
planner/responder use) into a LangGraph node closure, and ``build_graph`` wires the real one
when given a service (else a dependency-free default that fails soft).

**What the node does.** For a logged-in user it builds a **per-turn**
:class:`~app.tools.base.ToolRegistry` of the P8.3 dashboard tools bound to ``state.user_id``
(:func:`~app.tools.dashboard.build_dashboard_tools`), then drives a small, **bounded**
tool-calling loop against the router so the model can read the dashboard and/or propose
goals / milestones / tasks / progress based on the turn (and the planner's ``steps``). It
produces a :class:`~app.agents.state.WorkerResult` summarising what was read and/or proposed,
which the responder synthesises into the user-facing answer ("I added 3 tasks to your
'Become a data engineer' goal — review and approve them on your dashboard.").

**Never silent (§5.2).** The propose tools write ``source="ai"`` only (→ ``status="proposed"``);
this node adds no bypass. The summary it hands the responder always frames AI writes as
*proposed / pending approval*.

**Guests fail soft (§5.2: "dashboard requires an account").** When ``state.user_id is None``
the node **never** builds a tool (no write is even possible) and returns a
:class:`WorkerResult` carrying an ``error`` + a "sign in to use the dashboard" message — it
never calls the model and never crashes the graph. The same fail-soft posture covers an
unconfigured node (no service/router) and any unexpected error in the loop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.agents.state import AgentState, WorkerName, WorkerResult
from app.llm.errors import LLMError
from app.llm.types import ChatMessage
from app.tools.base import ToolRegistry
from app.tools.dashboard import build_dashboard_tools

if TYPE_CHECKING:
    from app.agents.planner import LLMCompleter
    from app.services.dashboard import DashboardService

logger = logging.getLogger(__name__)

__all__ = ["GUEST_MESSAGE", "make_dashboard_node"]

#: The fail-soft message a guest turn returns (§5.2: dashboard requires an account). Surfaced
#: to the responder as grounding so the answer invites the user to sign in — never a crash.
GUEST_MESSAGE = (
    "The dashboard (your saved development plan) is only available once you sign in. "
    "Ask the user to sign in to view or update their plan."
)

#: Max tool-calling rounds the node drives per turn (bounded — a read + a few proposes is
#: plenty; caps LLM/DB work and guarantees termination even if the model keeps calling tools).
DEFAULT_MAX_ITERATIONS = 3

#: Generation cap for each tool-call step. Roomy enough for several parallel tool calls in one
#: step (whose ``arguments`` JSON must not be truncated) plus a short wrap-up.
_MAX_TOKENS = 1024

_SYSTEM_PROMPT = (
    "You manage the user's career development-plan DASHBOARD using the provided tools. "
    "You can read their dashboard and PROPOSE goals, milestones, tasks, and progress notes. "
    "Everything you propose is created as a PENDING suggestion the user must approve on their "
    "dashboard — it is never applied silently, so make that clear.\n"
    "Guidance:\n"
    "- Call read_dashboard first when you need existing goal/milestone ids or to answer a "
    "question about what is on the plan.\n"
    "- Only propose changes the user actually asked for; do not invent goals.\n"
    "- A milestone or task must reference an existing goal_id (from read_dashboard).\n"
    "- When you are done, stop calling tools and briefly state what you read and/or proposed."
)


def make_dashboard_node(
    *,
    service: DashboardService | None = None,
    router: LLMCompleter | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> Any:
    """Build the LangGraph ``dashboard`` node closure, binding its collaborators (worker pattern).

    ``service`` (the shared :class:`~app.services.dashboard.DashboardService`) and ``router``
    (the failover :class:`~app.llm.router.LLMRouter`, injected as an :class:`LLMCompleter`) have
    **no** eager defaults — they are owned by the app and injected by ``build_graph(...)``. When
    either is unbound the node fails soft (never opens a rogue store / calls a missing model), so
    the import-time module graph still compiles. Guests fail soft before any tool is built.
    """

    async def dashboard_node(state: AgentState) -> dict[str, Any]:
        if state.user_id is None:
            # Guests are excluded from the dashboard (§5.2): never build a write-capable tool.
            return _node_update(
                WorkerResult(
                    worker=WorkerName.DASHBOARD,
                    content=GUEST_MESSAGE,
                    error="dashboard requires an account",
                )
            )
        if service is None or router is None:
            logger.warning(
                "dashboard node routed without a service/router; skipping "
                "(inject via build_graph(dashboard_service=..., router=...))"
            )
            return _node_update(
                WorkerResult(worker=WorkerName.DASHBOARD, error="dashboard worker not configured")
            )
        result = await _run_dashboard_turn(state, service, router, max_iterations)
        return _node_update(result)

    return dashboard_node


async def _run_dashboard_turn(
    state: AgentState,
    service: DashboardService,
    router: LLMCompleter,
    max_iterations: int,
) -> WorkerResult:
    """Drive the bounded tool-calling loop and summarise the actions (fails soft).

    Any error (router down, unexpected failure) yields a :class:`WorkerResult` carrying an
    ``error`` rather than raising out of the node — mirroring the RAG/market workers.
    """
    registry = ToolRegistry()
    for tool in build_dashboard_tools(state.user_id or "", service):
        registry.register(tool)

    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=_user_prompt(state)),
    ]
    actions: list[dict[str, Any]] = []
    try:
        for _ in range(max(1, max_iterations)):
            result = await router.complete(
                messages,
                tools=registry.schemas(),
                tool_choice="auto",
                temperature=0.0,
                max_tokens=_MAX_TOKENS,
            )
            if not result.tool_calls:
                break
            messages.append(
                ChatMessage(role="assistant", content=result.content, tool_calls=result.tool_calls)
            )
            for call in result.tool_calls:
                tool_msg = await registry.execute(call)
                messages.append(tool_msg)
                actions.append({"name": call.function.name, "result": tool_msg.content})
    except LLMError:
        logger.warning("dashboard tool-calling loop failed; returning empty result", exc_info=True)
        return WorkerResult(worker=WorkerName.DASHBOARD, error="dashboard worker failed")

    return _summarize(actions)


def _user_prompt(state: AgentState) -> str:
    """Assemble the turn prompt: the user's message + the planner's steps (if any)."""
    prompt = state.user_message.strip()
    steps = [s for s in (state.plan.steps if state.plan else []) if s.strip()]
    if steps:
        joined = "; ".join(steps)
        prompt = f"{prompt}\n\nPlan for this turn: {joined}"
    return prompt


def _summarize(actions: list[dict[str, Any]]) -> WorkerResult:
    """Turn the executed tool calls into grounding for the responder + structured ``data``.

    Reads through the tool results so the responder can tell the user exactly what was read and
    what was **proposed** (pending approval). Nothing here bypasses the ``proposed`` status —
    the propose tools already stamped it; this only reports it.
    """
    proposed: list[dict[str, Any]] = []
    read = False
    read_digest: str | None = None
    lines: list[str] = []
    for action in actions:
        payload = _load(action["result"])
        name = action["name"]
        if isinstance(payload, dict) and payload.get("error"):
            lines.append(f"- {name} failed: {payload['error']}")
            continue
        if name == "read_dashboard":
            read = True
            # Keep the latest read's rendered contents so the responder can ground its answer on
            # the actual goals/milestones/tasks/progress (not just "a read happened").
            if isinstance(payload, dict):
                read_digest = _render_dashboard_digest(payload)
            lines.append("- Read the user's current dashboard (contents below).")
        elif isinstance(payload, dict) and "proposed" in payload:
            kind = payload["proposed"]
            title = payload.get("title", "")
            proposed.append(payload)
            lines.append(f"- Proposed a {kind}: {title!r} (pending the user's approval).")
        elif isinstance(payload, dict) and payload.get("logged") == "progress":
            proposed.append(payload)
            lines.append("- Logged a progress note.")

    if not lines:
        content = (
            "No dashboard changes were made. Answer the user about their development plan and, "
            "if helpful, offer to add goals or tasks (which they would approve)."
        )
    else:
        header = "Dashboard actions taken this turn (AI proposals require the user's approval):"
        content = header + "\n" + "\n".join(lines)
    if read_digest:
        content = f"{content}\n\n{read_digest}"

    return WorkerResult(
        worker=WorkerName.DASHBOARD,
        content=content,
        data={"read": read, "proposed": proposed},
    )


def _render_dashboard_digest(summary: Mapping[str, Any]) -> str:
    """Render a ``read_dashboard`` payload into text grounding for the responder.

    Folds the actual goals (nested milestones/tasks) and progress rollup into the worker's
    ``content`` so a read-only turn ("what's on my dashboard?") can be answered — the responder
    grounds on ``WorkerResult.content`` only, never ``.data``.
    """
    lines = ["The user's current dashboard:"]
    goals = summary.get("goals") or []
    if not goals:
        lines.append("- (no goals yet)")
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        parts = [f"Goal: {goal.get('title', '(untitled)')!r}"]
        if goal.get("status"):
            parts.append(f"status={goal['status']}")
        if goal.get("target_role"):
            parts.append(f"target_role={goal['target_role']}")
        pct = goal.get("task_completion_pct")
        if pct is not None:
            parts.append(f"tasks {pct:.0f}% done")
        lines.append("- " + ", ".join(parts))
        for milestone in goal.get("milestones") or []:
            if isinstance(milestone, dict):
                lines.append(
                    f"    - milestone: {milestone.get('title', '')!r} "
                    f"({milestone.get('status', '')})"
                )
        for task in goal.get("tasks") or []:
            if isinstance(task, dict):
                lines.append(f"    - task: {task.get('title', '')!r} ({task.get('status', '')})")
    progress = summary.get("progress")
    if isinstance(progress, dict):
        lines.append(
            f"Progress: {progress.get('total_entries', 0)} entries, "
            f"{progress.get('current_streak_days', 0)}-day streak, "
            f"last entry {progress.get('last_entry_date') or 'never'}."
        )
    return "\n".join(lines)


def _load(raw: str) -> Any:
    """Parse a tool result's JSON content, tolerating a non-JSON payload (returns ``None``)."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _node_update(result: WorkerResult) -> dict[str, Any]:
    """Adapt a :class:`WorkerResult` into the dashboard node's partial update (P4-01 reducers)."""
    return {
        "worker_results": {WorkerName.DASHBOARD.value: result},
        "citations": list(result.citations),
    }
