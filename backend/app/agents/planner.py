"""Planner node — intent classify, decompose, route to workers, set a budget (design §3).

The planner is the first *reasoning* step of the multi-agent turn graph (design §3
Planner: *"classify intent (chat / job search / PDP / CV question / smalltalk),
decompose, route to workers, set an iteration/token budget"*). It replaces the P4-02
stub body: instead of a hardcoded decision, it asks the LLM to classify the turn and
outline a short plan, then derives a **conservative, deterministic** worker routing from
that intent and packages the whole thing as a :class:`~app.agents.state.PlannerDecision`
the graph fans out on (:func:`~app.agents.graph.route_after_planner`).

**Native tool-calling, no ReAct parsing (locked decision, CLAUDE.md §6 item 2).** Rather
than parse free text, the planner passes a single JSON-schema tool
(:data:`PLANNER_TOOL_SCHEMA`, shaped exactly like ``app/tools/`` schemas) and forces the
model to call it (``tool_choice`` pinned to that function). The structured
``ToolCall.function.arguments`` are then parsed into a decision — the same
schema-in / structured-out contract the rest of the app uses.

**Classification vs. routing split.** The LLM does what it is good at — assign one
:class:`~app.agents.state.Intent` and write human-readable steps — while the *worker
routing* is derived deterministically from that intent (:data:`_INTENT_WORKERS`). This
keeps routing conservative and unit-testable (the real RAG/web/job/PDP workers are still
stubs until P4-04..P4-06; the planner only decides whether to route to them) rather than
trusting the model to pick node names. The one place grounding is a judgement call —
a plain ``chat`` turn — is surfaced to the model as a ``needs_grounding`` flag.

**Fail-soft (a bad planner call must not 500 the turn).** If the router raises, returns
no tool call, or returns unparsable/invalid arguments, the planner falls back to a safe
default decision (``CHAT``, no workers) so the turn still reaches the responder. The
node never raises out of the graph.

**Dependency.** :class:`Planner` takes an :class:`LLMCompleter` (structurally the P1-02
:class:`~app.llm.router.LLMRouter` / P1-01 :class:`~app.llm.client.LLMClient` surface) by
constructor injection — not a hand-rolled client — so the design §6.6 option of pointing
the planner at a cheaper/faster model tier later is a wiring change, not a code change. A
:class:`Planner` instance *is* a LangGraph node (it is ``async``-callable with the state),
so ``build_graph(router=...)`` wires it straight in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from app.llm.errors import LLMError
from app.llm.types import ChatMessage, CompletionResult, ToolSchema

logger = logging.getLogger(__name__)

__all__ = [
    "LLMCompleter",
    "PLANNER_TOOL_NAME",
    "PLANNER_TOOL_SCHEMA",
    "Planner",
]


@runtime_checkable
class LLMCompleter(Protocol):
    """The minimal LLM surface the planner needs: one buffered tool-call completion.

    Kept as a structural :class:`Protocol` (not a hard import of ``LLMRouter``) so the
    planner depends on a capability, not a concrete class — the real
    :class:`~app.llm.router.LLMRouter` (and the single-model
    :class:`~app.llm.client.LLMClient`) satisfy this shape, and unit tests can inject a
    fake without touching HF. Mirrors :meth:`LLMRouter.complete` exactly.
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = ...,
        tool_choice: str | dict[str, Any] | None = ...,
        temperature: float | None = ...,
        max_tokens: int | None = ...,
    ) -> CompletionResult: ...


#: The function the planner forces the model to call (native tool-calling, no free text).
PLANNER_TOOL_NAME = "record_plan"

#: Ordered list of intent string values, used to constrain the tool schema ``enum`` to the
#: exact :class:`~app.agents.state.Intent` vocabulary (single source of truth).
_INTENT_VALUES: list[str] = [intent.value for intent in Intent]

#: The planner's tool schema — same OpenAI ``tools[]`` shape as ``app/tools/`` (P1-03).
#: The model returns the classified ``intent`` + a short ``steps`` plan; ``needs_grounding``
#: only matters for a ``chat`` intent (whether the answer needs the knowledge base).
PLANNER_TOOL_SCHEMA: ToolSchema = {
    "type": "function",
    "function": {
        "name": PLANNER_TOOL_NAME,
        "description": (
            "Record the plan for handling the user's latest message: its classified "
            "intent, a short ordered list of steps, and (for a chat intent) whether "
            "answering well needs knowledge-base grounding."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": _INTENT_VALUES,
                    "description": (
                        "The single best-fitting intent for the user's latest message."
                    ),
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "2-4 short, human-readable steps for how the assistant will "
                        "handle this turn. Do not answer the user here."
                    ),
                },
                "needs_grounding": {
                    "type": "boolean",
                    "description": (
                        "For a 'chat' intent only: true when answering well requires "
                        "retrieving from the knowledge base. Ignored for other intents."
                    ),
                },
            },
            "required": ["intent", "steps"],
            "additionalProperties": False,
        },
    },
}

#: Forced tool choice: the model MUST call ``record_plan`` (no free-text escape hatch).
_FORCED_TOOL_CHOICE: dict[str, Any] = {
    "type": "function",
    "function": {"name": PLANNER_TOOL_NAME},
}

#: Short, focused planning instruction — this is *not* the conversational system prompt,
#: only the classifier's brief.
PLANNER_SYSTEM_PROMPT = (
    "You are the planner for a career-coaching assistant. Read the user's latest "
    "message (and recent context) and call the record_plan function. Do not answer the "
    "user — only classify and plan.\n"
    "This assistant does career coaching and personal development ONLY. Your intent "
    "classification is also the topic guardrail, so tune for LOW false-positives: a "
    "legitimate career question must never be marked off_topic or job_hunting.\n"
    "Choose exactly one intent:\n"
    "- market_requirements: the user asks what a role/career requires — skills, "
    "background, or the gap to reach it (e.g. 'What skills do AI Solution Architects "
    "need?', 'How do I close the gap from PM to AI architect?').\n"
    "- pdp: the user wants a Personal Development Plan or career roadmap built "
    "(often from a CV / resume).\n"
    "- cv_question: the user asks about their own CV / resume content or how to "
    "improve it.\n"
    "- dashboard: the user asks about or wants to change their own development "
    "plan / dashboard — view it, add goals/milestones/tasks to their plan, or log "
    "progress (e.g. 'what's on my dashboard?', 'add these 5 tasks to my plan', 'mark "
    "the Docker task done', 'log that I finished the SQL course today').\n"
    "- chat: a substantive career question that needs an informative answer; set "
    "needs_grounding=true when answering well requires the knowledge base.\n"
    "- smalltalk: greetings, thanks, or chit-chat with no informational need.\n"
    "- job_hunting: the user wants to find/browse/apply to actual job openings or "
    "vacancies (e.g. 'find me AI architect jobs in Berlin', 'show me openings near "
    "me'). This is a near-miss — it will be redirected to market requirements, not "
    "refused. Use it ONLY for browse/apply-to-listings requests.\n"
    "- off_topic: anything outside career coaching / personal development — medical, "
    "legal, or financial advice, general chit-chat, homework (e.g. 'Is this rash "
    "serious?', 'Write my essay'). Refused.\n"
    "Return 2-4 concise steps describing how you will handle the turn."
)

#: Deterministic intent → worker routing (design §3 fan-out). Conservative on purpose:
#: ``chat`` is resolved separately via ``needs_grounding`` (see :func:`_workers_for`).
#: Both ``market_requirements`` and ``job_hunting`` route to the same MARKET_INTEL worker
#: (a cached ``role_profiles`` read) — the **responder** frames a job-hunting turn as a
#: redirect (design §7.4), the routing does not differ. ``off_topic`` runs no workers; the
#: graph short-circuits it to a canned refusal before the responder (design §7.4).
_INTENT_WORKERS: dict[Intent, list[WorkerName]] = {
    Intent.MARKET_REQUIREMENTS: [WorkerName.MARKET_INTEL],
    Intent.JOB_HUNTING: [WorkerName.MARKET_INTEL],
    Intent.PDP: [WorkerName.PDP_RESUME],
    Intent.CV_QUESTION: [WorkerName.RAG],
    Intent.DASHBOARD: [WorkerName.DASHBOARD],
    Intent.SMALLTALK: [],
    Intent.OFF_TOPIC: [],
}

#: Per-intent iteration budget (design §3: the planner "sets a budget"). Smalltalk /
#: off-topic need no workers/loops; retrieval-light chat/CV a couple; market-intel / PDP
#: the default cap.
_INTENT_MAX_ITERATIONS: dict[Intent, int] = {
    Intent.SMALLTALK: 1,
    Intent.OFF_TOPIC: 1,
    Intent.CHAT: 3,
    Intent.CV_QUESTION: 3,
    Intent.DASHBOARD: 3,
    Intent.MARKET_REQUIREMENTS: 5,
    Intent.JOB_HUNTING: 5,
    Intent.PDP: 5,
}

#: How many trailing history messages to hand the planner for context (bounded — the
#: classifier is a cheap step, it does not need the whole window).
_HISTORY_CONTEXT_MESSAGES = 6


def _workers_for(intent: Intent, *, needs_grounding: bool) -> list[WorkerName]:
    """Derive the worker routing for ``intent`` (design §3 fan-out mapping).

    A plain ``chat`` turn consults the RAG worker only when the model flagged the answer
    as needing grounding; every other intent maps deterministically via
    :data:`_INTENT_WORKERS`.
    """
    if intent is Intent.CHAT:
        return [WorkerName.RAG] if needs_grounding else []
    return list(_INTENT_WORKERS.get(intent, []))


def _safe_default_decision() -> PlannerDecision:
    """The fail-soft decision: treat the turn as chat, run no workers, reach the responder.

    Used whenever the LLM call raises or returns an unusable tool call — the turn still
    completes (design §3) instead of 500-ing the graph.
    """
    return PlannerDecision(
        intent=Intent.CHAT,
        steps=["Answer the user's message directly."],
        workers=[],
        max_iterations=_INTENT_MAX_ITERATIONS[Intent.CHAT],
    )


class Planner:
    """LLM-backed planner node: classify intent, decompose, route, budget (design §3).

    A :class:`Planner` instance is a LangGraph node — it is ``async``-callable with the
    :class:`~app.agents.state.AgentState` and returns the ``{"plan": ...}`` partial update
    the graph folds in. Construct it with an :class:`LLMCompleter` (the P1-02
    :class:`~app.llm.router.LLMRouter`) and hand it to ``build_graph(router=...)``.
    """

    def __init__(
        self,
        router: LLMCompleter,
        *,
        temperature: float = 0.0,
        max_tokens: int | None = 512,
    ) -> None:
        """Bind the planner to an LLM completer.

        Args:
            router: The LLM surface to classify with — normally the failover
                :class:`~app.llm.router.LLMRouter`. Injected (not constructed) so the
                design §6.6 cheaper-planner-model option is a wiring change later.
            temperature: Sampling temperature; ``0.0`` for a stable, near-deterministic
                classification.
            max_tokens: Generation cap for the (small) tool-call response.
        """
        self._router = router
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def __call__(self, state: AgentState) -> dict[str, Any]:
        """Run the planner as a graph node → the ``{"plan": PlannerDecision}`` update."""
        return {"plan": await self.plan(state)}

    async def plan(self, state: AgentState) -> PlannerDecision:
        """Classify + route the current turn, failing soft to a safe default.

        Forces the ``record_plan`` tool call, parses the structured arguments into a
        :class:`~app.agents.state.PlannerDecision`, and derives worker routing + budget
        from the classified intent. Any failure (router error, missing/invalid tool call)
        yields :func:`_safe_default_decision` so the node never raises.
        """
        try:
            result = await self._router.complete(
                self._build_messages(state),
                tools=[PLANNER_TOOL_SCHEMA],
                tool_choice=_FORCED_TOOL_CHOICE,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except LLMError:
            logger.warning("planner LLM call failed; using safe default", exc_info=True)
            return _safe_default_decision()

        decision = _parse_decision(result)
        if decision is None:
            logger.warning("planner returned no usable tool call; using safe default")
            return _safe_default_decision()
        return decision

    def _build_messages(self, state: AgentState) -> list[ChatMessage]:
        """Assemble the planner prompt: instruction + recalled memory + history + turn."""
        messages: list[ChatMessage] = [ChatMessage(role="system", content=PLANNER_SYSTEM_PROMPT)]
        memory_note = _memory_note(state)
        if memory_note:
            messages.append(ChatMessage(role="system", content=memory_note))
        if state.history:
            messages.extend(state.history[-_HISTORY_CONTEXT_MESSAGES:])
        messages.append(ChatMessage(role="user", content=state.user_message))
        return messages


def _memory_note(state: AgentState) -> str | None:
    """Render recalled learned memories into a short system note (empty until P9).

    The memory-recall node (P9) populates ``state.memory.memories``; folding them in here
    lets the planner personalise routing (e.g. a user who always wants job links). Until
    then this is a no-op because the slot is empty.
    """
    memories = [m for m in state.memory.memories if isinstance(m, str) and m.strip()]
    if not memories:
        return None
    joined = "; ".join(memories)
    return f"Known facts about the user (for context only): {joined}"


def _parse_decision(result: CompletionResult) -> PlannerDecision | None:
    """Parse the forced ``record_plan`` tool call into a decision, or ``None`` if unusable.

    Returns ``None`` (caller falls back) when there is no tool call, the arguments are not
    valid JSON object, or the ``intent`` is missing/unknown — never raises.
    """
    if not result.tool_calls:
        return None
    raw = result.tool_calls[0].function.arguments
    try:
        args = json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None

    intent_raw = args.get("intent")
    if not isinstance(intent_raw, str):
        return None
    try:
        intent = Intent(intent_raw)
    except ValueError:
        return None

    # ``steps`` is model-controlled: guard the type before iterating. A non-list value
    # (null / number / bool / a JSON string — the last of which would otherwise iterate
    # character-by-character) falls back to the synthesised default step below, so a
    # malformed argument shape can never raise out of the planner node (C1/C3).
    raw_steps = args.get("steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []
    steps = [s.strip() for s in raw_steps if isinstance(s, str) and s.strip()]
    needs_grounding = bool(args.get("needs_grounding", False))

    return PlannerDecision(
        intent=intent,
        steps=steps or [f"Handle the {intent.value} request."],
        workers=_workers_for(intent, needs_grounding=needs_grounding),
        max_iterations=_INTENT_MAX_ITERATIONS.get(intent, 5),
    )
