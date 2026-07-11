"""Typed shared LangGraph state threaded through the multi-agent graph (design §3).

This is the **single typed object** every node of the P4 graph reads and writes —
``recall → planner → workers → responder → guardrails → memory-writer`` (design §3:
*"State between nodes is a typed object (Pydantic) holding: user/session ids, message
history slice, planner decisions, per-worker results, citations, and safety verdicts."*).

**Why Pydantic (not a bare ``TypedDict``).** Design §3 explicitly calls for a *Pydantic*
state object, and LangGraph's :class:`~langgraph.graph.StateGraph` accepts a ``BaseModel``
as its schema, applying per-field **reducers** declared via :data:`typing.Annotated`
metadata exactly as it does for ``TypedDict`` states. Pydantic buys us validation,
enum coercion, and a first-class ``model_dump_json`` / ``model_validate_json`` round trip
— the last is load-bearing because the state crosses the Redis / Celery boundary
(memory-writer runs async, design §3) and must be JSON-serialisable.

**Parallel-worker safety (the main technical risk).** The planner fans out to workers
(RAG / Web / Job / PDP) that run **concurrently**; LangGraph executes concurrent nodes
in a superstep and folds each node's partial update into the state via the field's
reducer. Fields that several workers write are therefore ``Annotated`` with an
associative merge so no worker clobbers another's slice:

* :attr:`AgentState.worker_results` — a per-worker dict merged key-wise
  (:func:`merge_worker_results`); each worker owns its own key.
* :attr:`AgentState.citations` — list-concatenated (:func:`operator.add`) so every
  worker's grounding sources accumulate.

Single-writer fields (planner decision, guardrail verdicts, the final response) need no
reducer — last write wins, and only one node writes them.

Scope note: this module is **state-only** (P4-01). The graph wiring and the
planner/worker/responder nodes are separate P4 tasks that *consume* this object; the
guardrail (P10) and memory (P9) fields are reserved here so those phases have a home to
write into without reshaping the state later.
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.llm.types import ChatMessage
from app.schemas.auth import SessionRole


class Intent(StrEnum):
    """The user-turn class the planner assigns (design §3 Planner: *"classify intent
    (chat / job search / PDP / CV question / smalltalk)"*)."""

    CHAT = "chat"
    JOB_SEARCH = "job_search"
    PDP = "pdp"
    CV_QUESTION = "cv_question"
    SMALLTALK = "smalltalk"


class WorkerName(StrEnum):
    """The worker/agent nodes the planner may route to (design §3 node list).

    Used both as the :attr:`PlannerDecision.workers` routing vocabulary and as the key
    space of :attr:`AgentState.worker_results`. A :class:`~enum.StrEnum` member *is* a
    ``str``, so it can be used directly as a dict key and serialises to its plain value.
    """

    RAG = "rag"
    WEB_SEARCH = "web_search"
    JOB_SEARCH = "job_search"
    PDP_RESUME = "pdp_resume"


class GuardrailStage(StrEnum):
    """Which guardrail pass produced a :class:`SafetyVerdict` (design §3 / §7: pre-input
    and post-output safety)."""

    INPUT = "input"
    OUTPUT = "output"


class Citation(BaseModel):
    """One grounding source a worker used, surfaced by the Response Agent (design §3:
    *"synthesize, cite sources"*).

    All fields are optional so any worker can emit whatever provenance it has (a KB
    chunk id, a crawled URL, a job-listing link) without a rigid shape.
    """

    source_id: str | None = None
    title: str | None = None
    url: str | None = None
    snippet: str | None = None
    #: Which worker contributed this citation (traceability across parallel workers).
    worker: WorkerName | None = None


class WorkerResult(BaseModel):
    """One worker node's output slice (design §3: *"per-worker results"*).

    Stored under :attr:`AgentState.worker_results` keyed by :class:`WorkerName`. Carries
    the worker's synthesised text and/or structured ``data`` plus its own citations, so
    the responder can merge outputs and attribute sources. ``error`` lets a worker fail
    soft (record the failure in state) rather than aborting the whole graph.
    """

    worker: WorkerName
    content: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class PlannerDecision(BaseModel):
    """The planner's routing decision (design §3 Planner: *"classify intent, decompose,
    route to workers, set an iteration/token budget"*).

    Single-writer: only the planner node writes this, so it needs no reducer.
    """

    intent: Intent
    #: Ordered decomposition of the turn into steps (human-readable plan).
    steps: list[str] = Field(default_factory=list)
    #: Which workers to run (and, by list order, a suggested order).
    workers: list[WorkerName] = Field(default_factory=list)
    #: Iteration budget for the graph (design §3: planner *"sets a budget"*).
    max_iterations: int = Field(default=5, ge=1)
    #: Optional token budget for the turn; ``None`` = provider/router default.
    token_budget: int | None = Field(default=None, ge=1)


class SafetyVerdict(BaseModel):
    """A guardrail outcome for one stage (design §3 / §7 pre + post safety).

    Placeholder-but-shaped: P4 wires only a minimal guardrail hook, while P10 lands the
    full classifier — both write this same shape into
    :attr:`AgentState.input_safety` / :attr:`AgentState.output_safety`.
    """

    stage: GuardrailStage
    #: Whether the turn may proceed / be returned. Default-open so an un-run guardrail
    #: does not block the pipeline before P10 fills it in.
    allowed: bool = True
    #: Triggered category labels (e.g. ``jailbreak``, ``pii``, ``injection``).
    categories: list[str] = Field(default_factory=list)
    #: Human-readable reason when ``allowed`` is ``False``.
    reason: str | None = None


class MemoryContext(BaseModel):
    """Recalled personalization context fed in before planning (design §3 Memory recall
    → §5.4).

    Reserved for P9: the memory-recall step populates ``preferences`` (explicit,
    user-editable settings — tone/formality/language) and ``memories`` (top-k learned
    facts retrieved by similarity). Unused until P9, but present so recall has a home.
    """

    preferences: dict[str, Any] = Field(default_factory=dict)
    memories: list[str] = Field(default_factory=list)


def merge_worker_results(
    existing: dict[str, WorkerResult],
    incoming: dict[str, WorkerResult],
) -> dict[str, WorkerResult]:
    """Reducer for :attr:`AgentState.worker_results` — key-wise dict merge.

    LangGraph calls this once per node update in a superstep. Because each worker writes
    under its **own** :class:`WorkerName` key, a plain right-biased merge lets parallel
    workers accumulate without clobbering one another. Associative for the same key set,
    which is what concurrent fan-in requires.
    """

    return {**existing, **incoming}


class AgentState(BaseModel):
    """The typed object threaded through every node of the P4 graph (design §3).

    Construction only requires the turn essentials (``session_id`` + ``user_message``);
    every downstream slice defaults empty and is filled by the node that owns it.
    """

    # --- identity (design §3: "user/session ids") ------------------------------- #
    #: The session handle; also the server-side state / rate-limit key (§4, P3-04).
    session_id: str = Field(..., min_length=1, max_length=64)
    #: Logged-in ``users.id``; ``None`` for guests (§4 — guests are Redis-only).
    user_id: str | None = Field(default=None, max_length=64)
    #: Identity kind, reused verbatim from the auth vocabulary (no parallel copy).
    role: SessionRole = "guest"

    # --- current turn ----------------------------------------------------------- #
    #: The raw user input for this turn.
    user_message: str
    #: The stable, feedback-ready id of the assistant answer this turn produces
    #: (design §5.5). Reuses the P1 ``message_id`` convention
    #: (:attr:`app.llm.types.ChatMessage.message_id`) — not a new id. Set once by the
    #: responder and stamped onto the persisted assistant message.
    message_id: str | None = None
    #: Recent conversation slice, already in LLM-ready form (each
    #: :class:`~app.llm.types.ChatMessage` renders via ``to_openai``). This is the
    #: "message history slice" of design §3 — a bounded window, not the full history.
    history: list[ChatMessage] = Field(default_factory=list)

    # --- memory recall (design §3 → §5.4; reserved for P9) ---------------------- #
    memory: MemoryContext = Field(default_factory=MemoryContext)

    # --- planner decision (single writer) --------------------------------------- #
    plan: PlannerDecision | None = None

    # --- worker outputs (parallel writers → reducers) --------------------------- #
    #: Per-worker results keyed by :class:`WorkerName`; merged key-wise so concurrent
    #: workers never clobber each other (:func:`merge_worker_results`).
    worker_results: Annotated[dict[str, WorkerResult], merge_worker_results] = Field(
        default_factory=dict
    )
    #: Grounding sources accumulated across all workers (list-concatenated so parallel
    #: contributions add up rather than overwrite).
    citations: Annotated[list[Citation], operator.add] = Field(default_factory=list)

    # --- responder output (single writer) --------------------------------------- #
    #: The synthesised assistant answer (design §3 Response Agent).
    response: str | None = None
    #: Why the turn ended (mirrors the LLM finish reason for the responder/SSE ``done``).
    finish_reason: str | None = None

    # --- guardrail verdicts (single writer per stage; reserved fully for P10) ---- #
    input_safety: SafetyVerdict | None = None
    output_safety: SafetyVerdict | None = None
