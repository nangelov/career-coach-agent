"""LangGraph wiring for the multi-agent turn graph (design §3).

This module assembles the :class:`~langgraph.graph.StateGraph` that threads the
:class:`~app.agents.state.AgentState` object through the node sequence design §3
prescribes::

    Guardrails(input) → Memory recall → Planner
        → {RAG, Web Searcher, Job Search, PDP/Resume}  (conditional fan-out, parallel)
        → Response Agent (fan-in)
        → Guardrails(output) → Memory writer (terminal; async/Celery in P9)

**What is real here vs. what is a placeholder.** This task (P4-02) owns the *graph
shape* — the nodes, edges, conditional fan-out and fan-in — and nothing else. Every
node body below is a **thin, deliberately-temporary stub** that produces a minimal,
plausible :class:`AgentState` update so the wiring can be built and tested end-to-end
*now*, before the real agents exist. The stubs are meant to be **replaced in place** by
later tasks **without changing this module's wiring, edges, or conditional-routing
contract**:

* ``rag_node``                → **real** (P4-04): built by
                              :func:`app.agents.rag_agent.make_rag_node`, embed + retrieve
                              from the pgvector KB with citations.
* ``web_search_node``         → **real** (P4-05): built by
                              :func:`app.agents.web_searcher.make_web_search_node`, search the
                              web + crawl the top hits with citations.
* ``job_search_node`` / ``pdp_resume_node``
                              → real workers (P4-06); still stubs here
* ``responder_node``          → **real** as of P4-06: the LLM-backed
                              :class:`app.agents.responder.Responder` (synthesis + citation +
                              streaming), wired via ``build_graph(responder_router=...)`` and
                              driven token-by-token by :func:`stream_graph`. ``responder_node``
                              remains as the dependency-free no-router default.
* ``input_guardrail_node``    → **minimal-real** as of P4-08: runs the deterministic
                              :func:`app.guardrails.screen_input` deny-list heuristic and its
                              verdict is routed on (:func:`route_after_input_guardrail`) so a
                              blocked turn short-circuits to the terminal tail before any LLM
                              call. Full classifier is P10 (same ``SafetyVerdict`` hook).
* ``output_guardrail_node``   → real safety classifier (P10; hook shape is stable)
* ``memory_recall_node`` / ``memory_writer_node``
                              → real LangMem recall/learn (P9; writer runs async/Celery)

Each stub is annotated with the task that replaces it. A replacement task should swap
the *body* of its node function and leave the graph topology untouched.

**Conditional fan-out.** :func:`route_after_planner` uses LangGraph's :class:`Send` API
so only the workers the planner selected (``PlannerDecision.workers``) are dispatched —
unselected workers never run. When the planner selects no workers the turn routes
straight to the responder.

**Fan-in safety.** All worker nodes converge on the responder. Concurrent worker writes
to ``worker_results`` / ``citations`` merge via the reducers declared on
:class:`AgentState` (P4-01) — this module relies on that and does not re-derive it.

**Construction.** The production graph is compiled **once** at import time
(:data:`graph`). :func:`build_graph` is the factory behind it. It exposes two ways to
supply the planner node: a ``router`` (the P1-02 :class:`~app.llm.router.LLMRouter`),
which wires the **real** LLM-backed :class:`~app.agents.planner.Planner` (P4-03), and a
lower-level ``planner`` override used as a test seam to drive specific routings through
the *real* compiled graph. When neither is given (the module-level :data:`graph` built at
import, before any router exists) the planner falls back to :func:`planner_node`, a
dependency-free safe default so import stays side-effect-free. Nothing here is wired into
the P1 ``POST /api/chat`` endpoint yet — that integration (which will pass ``router=``)
is a later task.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, TypeAlias

from langgraph.graph import END, START, StateGraph
from langgraph.graph._node import StateNode
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

if TYPE_CHECKING:
    import httpx

    from app.llm.embeddings import EmbeddingClient

from app.agents.planner import LLMCompleter, Planner
from app.agents.rag_agent import SessionProvider, make_rag_node
from app.agents.responder import LLMResponder, Responder
from app.agents.state import (
    AgentState,
    Citation,
    Intent,
    PlannerDecision,
    WorkerName,
    WorkerResult,
)
from app.agents.web_searcher import SearchRunner, make_web_search_node
from app.guardrails import REFUSAL_MESSAGE, screen_input, screen_output
from app.llm.types import StreamChunk

#: A node returns a **partial** state update as a mapping; LangGraph folds it into the
#: shared :class:`AgentState` via each field's reducer (or last-write-wins).
NodeUpdate = dict[str, Any]
#: A LangGraph node accepting our state — the type of the ``planner`` test seam and the
#: shape every node ``def`` in this module satisfies. ``StateNode`` comes from langgraph's
#: private ``langgraph.graph._node`` module; the explicit ``TypeAlias`` marker declares this
#: unambiguously as a type alias so mypy accepts ``PlannerNode`` in annotations regardless of
#: how that private symbol is inferred.
PlannerNode: TypeAlias = StateNode[AgentState, Any]

# --------------------------------------------------------------------------- #
# Node names (single source of truth for edges + routing).                    #
# Worker node names are the ``WorkerName`` values so the planner's routing     #
# vocabulary maps 1:1 onto the graph nodes it dispatches.                      #
# --------------------------------------------------------------------------- #
INPUT_GUARDRAIL = "input_guardrail"
MEMORY_RECALL = "memory_recall"
PLANNER = "planner"
RESPONDER = "responder"
OUTPUT_GUARDRAIL = "output_guardrail"
MEMORY_WRITER = "memory_writer"

#: The four worker node names, in a stable order (also the fan-in edge set).
WORKER_NODES: tuple[str, ...] = tuple(w.value for w in WorkerName)


# --------------------------------------------------------------------------- #
# Guardrails.                                                                   #
# Input (P4-08): a **minimal, real** deterministic deny-list heuristic          #
# (app.guardrails.screen_input) — the cheap coarse net, not the P10 classifier. #
# Its verdict is routed on (route_after_input_guardrail): a blocked turn         #
# short-circuits to the terminal tail *before* the planner/workers/responder,    #
# so no LLM call is wasted and no worker side effect runs. Output (P10): still a   #
# pass-through stub. Both write the same SafetyVerdict shape P10 replaces in place. #
# --------------------------------------------------------------------------- #
def input_guardrail_node(state: AgentState) -> NodeUpdate:
    """Minimal input safety screen (P4-08, design §7). Blocks canonical jailbreak /
    prompt-injection phrasing before any planner/worker/responder work runs.

    Runs the deterministic :func:`app.guardrails.screen_input` heuristic over the raw
    ``user_message``. When it **allows** the turn, only the verdict is written and the graph
    proceeds normally (``route_after_input_guardrail`` → memory recall). When it **blocks**,
    the node additionally stamps a generic, canned refusal into ``response`` (plus a
    ``"blocked"`` finish reason and the turn's ``message_id``) so the short-circuit route
    (→ output guardrail → memory writer → END, skipping planner/workers/responder) yields a
    well-formed terminal state without any LLM call. The verdict's internal
    ``categories``/``reason`` stay on ``input_safety`` for telemetry and are never surfaced
    to the user — only :data:`~app.guardrails.REFUSAL_MESSAGE` is. Full classifier is P10.
    """
    verdict = screen_input(state.user_message)
    if verdict.allowed:
        return {"input_safety": verdict}
    return {
        "input_safety": verdict,
        "response": REFUSAL_MESSAGE,
        "finish_reason": "blocked",
        "message_id": state.message_id or uuid.uuid4().hex,
    }


def output_guardrail_node(state: AgentState) -> NodeUpdate:
    """Minimal output safety net (SEC-02, design §7.3 point 4). Coarse placeholder — P10.

    Runs the deterministic :func:`app.guardrails.screen_output` heuristic over the composed
    ``response``, **stripping** any canonical injection phrasing the answer echoed back out of
    untrusted grounding material (a crawled page / CV that said "ignore previous instructions").
    Writes the OUTPUT :class:`SafetyVerdict` for telemetry and, only when a redaction happened,
    the scrubbed ``response`` (a scrub neutralises rather than blocks — the answer still returns,
    just cleaned). Anything the deny-list does not recognise passes through unchanged
    (default-open). Full injection/leakage detection is P10 (same ``SafetyVerdict`` hook).

    Note: this node sees the **buffered** response (:func:`run_graph`). On the streaming path
    (:class:`GraphTurnStreamer` → :class:`~app.services.chat.ChatService`) the same
    :func:`~app.guardrails.screen_output` net is applied to the token stream as it is emitted.
    """
    screen = screen_output(state.response or "")
    update: NodeUpdate = {"output_safety": screen.verdict}
    if screen.modified:
        update["response"] = screen.text
    return update


# --------------------------------------------------------------------------- #
# Memory stubs — real LangMem recall/learn lands in P9 (design §5.4-5.5).      #
# --------------------------------------------------------------------------- #
def memory_recall_node(state: AgentState) -> NodeUpdate:
    """[STUB → P9] Recall user prefs + learned memories into context.

    No-op today: the ``memory`` slot is already default-constructed on the state, so
    planning proceeds with empty personalization until P9 populates it here.
    """
    return {}


def memory_writer_node(state: AgentState) -> NodeUpdate:
    """[STUB → P9] Terminal post-turn memory writer.

    No-op today. Positioned as the terminal node (post-response) so that when P9 makes
    it extract durable prefs + fold in thumb up/down feedback — running async via Celery
    — the graph shape does not need to change.
    """
    return {}


# --------------------------------------------------------------------------- #
# Default planner — no-router fallback.                                        #
# The real LLM-backed planner (P4-03) is app.agents.planner.Planner, wired via  #
# build_graph(router=...). This node is the safe default used only when no       #
# router/planner is supplied (the import-time module graph, before the chat      #
# endpoint injects a router): it classifies nothing and runs no workers so the    #
# turn still reaches the responder — the same posture Planner fails soft to.       #
# --------------------------------------------------------------------------- #
def planner_node(state: AgentState) -> NodeUpdate:
    """No-router default: route straight to the responder (no worker fan-out).

    Real intent classification / decomposition / budgeting lives in
    :class:`app.agents.planner.Planner`; supply ``build_graph(router=...)`` to use it.
    """
    decision = PlannerDecision(
        intent=Intent.CHAT,
        steps=["Answer the user's message directly."],
        workers=[],
    )
    return {"plan": decision}


# --------------------------------------------------------------------------- #
# Worker nodes.                                                                #
# The RAG worker (P4-04) and the Web Searcher (P4-05) are real: each node is     #
# built by its module's ``make_*`` factory, binding collaborators injected by     #
# build_graph (production singletons or test fakes). The remaining two are still   #
# thin named stubs delegating to one shared builder (DRY) — each writes a canned    #
# WorkerResult under its own key + one citation, exercising the P4-01 fan-in         #
# reducers — to be swapped in place by P4-06.                                         #
# --------------------------------------------------------------------------- #
#: The default RAG node used by the import-time module graph: no DB provider bound,
#: so it fails soft if routed (the chat wiring injects the shared provider later via
#: ``build_graph(db=...)``). ``build_graph`` swaps in a provider-bound node when given
#: ``embedder=`` / ``db=`` (production singletons or test fakes).
rag_node = make_rag_node()

#: The default Web Searcher node used by the import-time module graph: no search tool /
#: http client bound, so it lazily builds the settings-configured ``InternetSearchTool``
#: per call and fails soft when ``SEARXNG_URL`` is unset. ``build_graph`` swaps in an
#: injected node when given ``search_tool=`` / ``http_client=`` (production or test fakes).
web_search_node = make_web_search_node()


def _worker_update(name: WorkerName, user_message: str) -> NodeUpdate:
    """Canned partial update for worker ``name`` (shared stub body; DRY)."""
    result = WorkerResult(
        worker=name,
        content=f"[stub:{name.value}] result for {user_message!r}",
        citations=[Citation(worker=name, title=f"stub-{name.value}")],
    )
    return {
        # keyed by the worker's own name → key-wise merge, no clobbering.
        "worker_results": {name.value: result},
        # list-concatenated across workers.
        "citations": [Citation(worker=name, title=f"stub-{name.value}")],
    }


def job_search_node(state: AgentState) -> NodeUpdate:
    """[STUB → P4-06] Job search worker: query job APIs, normalize, match-score."""
    return _worker_update(WorkerName.JOB_SEARCH, state.user_message)


def pdp_resume_node(state: AgentState) -> NodeUpdate:
    """[STUB → P4-06] PDP / Resume worker: parse CV, skills-gap, build PDP."""
    return _worker_update(WorkerName.PDP_RESUME, state.user_message)


# --------------------------------------------------------------------------- #
# Default responder — no-router fallback.                                      #
# The real LLM-backed Response Agent (P4-06) is app.agents.responder.Responder, #
# wired via build_graph(responder_router=...). This node is the dependency-free  #
# deterministic default used only when no responder router is supplied (the      #
# import-time module graph, before the chat endpoint injects a router): it        #
# merges the already-fanned-in worker contents into one answer so the turn still   #
# completes without an LLM — the same posture planner_node holds for the planner.   #
# --------------------------------------------------------------------------- #
def responder_node(state: AgentState) -> NodeUpdate:
    """No-router default: merge the (already-merged) worker contents into one answer.

    Deterministic and LLM-free: echoes every dispatched worker's content slice (proving the
    P4-01 fan-in reducers fed them here) and stamps a stable ``message_id`` (design §5.5
    feedback id) + a ``stop`` finish reason. Real synthesis/citation/streaming lives in
    :class:`app.agents.responder.Responder`; supply ``build_graph(responder_router=...)`` to
    use it. ``citations`` are left untouched so the accumulated worker citations pass through.
    """
    parts = [r.content for r in state.worker_results.values() if r.content]
    response = " | ".join(parts) if parts else f"[direct] {state.user_message}"
    return {
        "response": response,
        "finish_reason": "stop",
        "message_id": state.message_id or uuid.uuid4().hex,
    }


# --------------------------------------------------------------------------- #
# Conditional routing after the input guardrail (P4-08).                       #
# --------------------------------------------------------------------------- #
def route_after_input_guardrail(state: AgentState) -> str:
    """Block a disallowed turn before the planner/workers/responder (design §7).

    Reads the verdict :func:`input_guardrail_node` just stamped: when the turn is **blocked**
    (``input_safety.allowed is False``) it routes straight to :data:`OUTPUT_GUARDRAIL` — the
    terminal tail — so the planner, every worker, and the responder are skipped entirely (no
    wasted LLM call, no worker side effect); the canned refusal the guardrail node placed in
    ``response`` is what the turn returns. When **allowed** (the default-open common case) it
    proceeds to :data:`MEMORY_RECALL` exactly as before — the legitimate path is unchanged.
    """
    verdict = state.input_safety
    if verdict is not None and not verdict.allowed:
        return OUTPUT_GUARDRAIL
    return MEMORY_RECALL


# --------------------------------------------------------------------------- #
# Conditional fan-out from the planner.                                        #
# --------------------------------------------------------------------------- #
def route_after_planner(state: AgentState) -> list[Send]:
    """Dispatch only the workers the planner selected (design §3 fan-out).

    Returns one :class:`Send` per selected worker so LangGraph runs *only* those nodes
    concurrently; the fan-in edges (worker → responder) then converge them. When the
    planner selects no workers, route straight to the responder so the turn still
    completes.
    """
    workers = state.plan.workers if state.plan else []
    if not workers:
        return [Send(RESPONDER, state)]
    # de-duplicate while preserving order (a worker only runs once per turn).
    seen: set[str] = set()
    sends: list[Send] = []
    for w in workers:
        if w.value not in seen:
            seen.add(w.value)
            sends.append(Send(w.value, state))
    return sends


# --------------------------------------------------------------------------- #
# Graph assembly.                                                              #
# --------------------------------------------------------------------------- #
def build_graph(
    *,
    router: LLMCompleter | None = None,
    planner: PlannerNode | None = None,
    responder_router: LLMResponder | None = None,
    embedder: EmbeddingClient | None = None,
    db: SessionProvider | None = None,
    search_tool: SearchRunner | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> CompiledStateGraph[AgentState]:
    """Assemble and compile the multi-agent turn graph (design §3).

    Planner node resolution, in priority order:

    * ``planner`` — a node override; the **test seam** used to drive specific routings
      through the real compiled graph (takes precedence when given).
    * ``router`` — an :class:`~app.llm.router.LLMRouter` (P1-02); wires the **real**
      LLM-backed :class:`~app.agents.planner.Planner` (P4-03). This is how the chat
      endpoint will build a planning graph.
    * neither — falls back to :func:`planner_node`, the dependency-free safe default, so
      the module-level :data:`graph` compiles at import without a router.

    RAG worker resolution (P4-04): when ``embedder`` and/or ``db`` are supplied they are
    bound into a fresh :func:`~app.agents.rag_agent.make_rag_node` closure (the chat wiring
    passes the app's shared :class:`~app.repositories.postgres.PostgresConnectionProvider`;
    tests inject fakes). When neither is given the module-default :data:`rag_node` is used —
    it fails soft if routed without a provider, so the import-time :data:`graph` still
    compiles and unit tests that do not route RAG are unaffected.

    Web Searcher resolution (P4-05): symmetric — when ``search_tool`` and/or ``http_client``
    are supplied they are bound into a fresh
    :func:`~app.agents.web_searcher.make_web_search_node` closure (tests inject a fake search
    tool + a mock ``httpx`` transport). When neither is given the module-default
    :data:`web_search_node` is used — it lazily builds the settings-configured search tool and
    fails soft when SearXNG is unconfigured.

    Responder resolution (P4-06): when ``responder_router`` is supplied it wires the **real**
    LLM-backed :class:`~app.agents.responder.Responder` (synthesis + citation) as the RESPONDER
    node; when omitted the graph falls back to the dependency-free deterministic
    :func:`responder_node` (so the import-time :data:`graph` still compiles without an LLM). The
    token-streaming counterpart the chat endpoint will use is :func:`stream_graph`.
    """
    resolved_planner: PlannerNode
    if planner is not None:
        resolved_planner = planner
    elif router is not None:
        resolved_planner = Planner(router)
    else:
        resolved_planner = planner_node

    resolved_responder: StateNode[AgentState, Any] = (
        Responder(responder_router) if responder_router is not None else responder_node
    )

    resolved_rag = (
        make_rag_node(embedder=embedder, db=db)
        if (embedder is not None or db is not None)
        else rag_node
    )

    resolved_web_search = (
        make_web_search_node(search_tool=search_tool, http_client=http_client)
        if (search_tool is not None or http_client is not None)
        else web_search_node
    )

    builder: StateGraph[AgentState] = StateGraph(AgentState)

    builder.add_node(INPUT_GUARDRAIL, input_guardrail_node)
    builder.add_node(MEMORY_RECALL, memory_recall_node)
    builder.add_node(PLANNER, resolved_planner)
    builder.add_node(WorkerName.RAG.value, resolved_rag)
    builder.add_node(WorkerName.WEB_SEARCH.value, resolved_web_search)
    builder.add_node(WorkerName.JOB_SEARCH.value, job_search_node)
    builder.add_node(WorkerName.PDP_RESUME.value, pdp_resume_node)
    builder.add_node(RESPONDER, resolved_responder)
    builder.add_node(OUTPUT_GUARDRAIL, output_guardrail_node)
    builder.add_node(MEMORY_WRITER, memory_writer_node)

    # Pre-planner chain: input safety → recall → planner — but the input guardrail may
    # short-circuit a blocked turn straight to the terminal tail (output guardrail → memory
    # writer), skipping planner/workers/responder (P4-08).
    builder.add_edge(START, INPUT_GUARDRAIL)
    builder.add_conditional_edges(
        INPUT_GUARDRAIL,
        route_after_input_guardrail,
        [MEMORY_RECALL, OUTPUT_GUARDRAIL],
    )
    builder.add_edge(MEMORY_RECALL, PLANNER)

    # Conditional fan-out to the selected workers (or straight to the responder).
    builder.add_conditional_edges(
        PLANNER,
        route_after_planner,
        [*WORKER_NODES, RESPONDER],
    )

    # Fan-in: every worker converges on the responder (waits for all dispatched).
    for worker_name in WORKER_NODES:
        builder.add_edge(worker_name, RESPONDER)

    # Post-response tail: output safety → terminal memory writer.
    builder.add_edge(RESPONDER, OUTPUT_GUARDRAIL)
    builder.add_edge(OUTPUT_GUARDRAIL, MEMORY_WRITER)
    builder.add_edge(MEMORY_WRITER, END)

    return builder.compile()


#: The production graph — compiled **once** at import, reused across all turns.
graph: CompiledStateGraph[AgentState] = build_graph()


async def run_graph(state: AgentState) -> AgentState:
    """Run one turn through the compiled multi-agent graph and return the final state.

    The stable entrypoint the (later) ``POST /api/chat`` v2 wiring will call. Returns a
    validated :class:`AgentState` (LangGraph hands back the schema object; we re-validate
    to normalise it into a first-party model regardless of the runtime's internal form).
    """
    result = await graph.ainvoke(state)
    return AgentState.model_validate(result)


class GraphTurnStreamer:
    """Reusable, compiled-**once** streaming runner for one graph turn (design §3).

    The production counterpart to the free :func:`stream_graph` function: it compiles the
    pre-responder graph **once at construction** (the composition root wires it) and reuses it
    across every turn, rather than rebuilding a graph per call. This is the "compiled-graph
    reuse" :func:`stream_graph` deferred to the chat-endpoint integration. The
    :class:`~app.services.chat.ChatService` depends on this shape (a structural ``GraphTurnRunner``
    seam) so it can be driven with a fake in unit tests.

    The turn is split into two explicit phases so a latent multi-agent turn stays cancellable
    and its plan/worker steps can be surfaced *before* tokens stream:

    * :meth:`plan` — run the pre-responder nodes (guardrails → recall → planner → workers) to
      completion and return the merged :class:`AgentState` (plan + ``worker_results`` +
      accumulated ``citations``). Its deterministic placeholder ``response`` is discarded.
    * :meth:`stream_response` — stream the **real** :class:`~app.agents.responder.Responder`'s
      token deltas over that merged state (fails soft — never raises).
    """

    def __init__(
        self,
        *,
        responder_router: LLMResponder,
        router: LLMCompleter | None = None,
        planner: PlannerNode | None = None,
        embedder: EmbeddingClient | None = None,
        db: SessionProvider | None = None,
        search_tool: SearchRunner | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # Compile the pre-responder graph once (LLM-free deterministic responder tail — its
        # placeholder answer is discarded; the real Responder streams below).
        self._pre_graph = build_graph(
            router=router,
            planner=planner,
            embedder=embedder,
            db=db,
            search_tool=search_tool,
            http_client=http_client,
        )
        self._responder = Responder(responder_router)
        self._responder_router = responder_router

    async def plan(self, state: AgentState) -> AgentState:
        """Run the pre-responder pipeline and return the merged turn state."""
        return AgentState.model_validate(await self._pre_graph.ainvoke(state))

    def stream_response(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        """Stream the responder's token deltas over the merged ``state`` (fails soft).

        For a turn the input guardrail **blocked** (``input_safety.allowed is False``) the
        real responder is skipped entirely — no LLM call — and the canned refusal
        (:data:`~app.guardrails.REFUSAL_MESSAGE`, already stamped onto ``state.response`` by
        the guardrail node) is emitted as a single terminal chunk. A blocked turn is a
        *successful* turn carrying a policy answer, so it streams like any other (the chat
        service turns it into ``token`` + ``done``, not an ``error``).
        """
        verdict = state.input_safety
        if verdict is not None and not verdict.allowed:
            return self._stream_refusal(state)
        return self._responder.stream(state)

    async def _stream_refusal(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        """Emit the guardrail's canned refusal as one terminal chunk (no LLM call)."""
        yield StreamChunk(
            content=state.response or REFUSAL_MESSAGE,
            finish_reason=state.finish_reason or "blocked",
        )

    async def aclose(self) -> None:
        """Release the underlying LLM router (best-effort; shared, closed once on shutdown)."""
        aclose = getattr(self._responder_router, "aclose", None)
        if aclose is not None:
            await aclose()


async def stream_graph(
    state: AgentState,
    *,
    responder_router: LLMResponder,
    router: LLMCompleter | None = None,
    planner: PlannerNode | None = None,
    embedder: EmbeddingClient | None = None,
    db: SessionProvider | None = None,
    search_tool: SearchRunner | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> AsyncIterator[StreamChunk | AgentState]:
    """Run one turn and **stream** the responder's tokens (design §3 "streams tokens").

    The token-streaming counterpart to :func:`run_graph`. The compiled-once, reusable version
    the ``POST /api/chat`` service uses is :class:`GraphTurnStreamer`; this free function is the
    convenience form (it builds a fresh :class:`GraphTurnStreamer` per call) kept for callers /
    tests that want a one-shot stream.

    Yield contract — a small, documented union:

    * zero or more :class:`~app.llm.types.StreamChunk` — the responder's incremental token
      deltas, in order, as the LLM emits them;
    * then exactly one **final** :class:`AgentState` — the terminal turn state (merged
      ``worker_results`` + accumulated ``citations`` + ``message_id`` + the assembled
      ``response`` + ``finish_reason``). It is always the last item yielded; a consumer streams
      the ``StreamChunk`` items to the client and keeps the trailing ``AgentState`` for
      persistence / citation rendering.

    Mechanics (see :class:`GraphTurnStreamer`): the pre-responder nodes run to completion via
    the deterministic, LLM-free graph purely to obtain the merged worker state; the real
    :class:`~app.agents.responder.Responder` then streams over it. Fails soft: the responder
    degrades to a fallback chunk rather than raising.
    """
    streamer = GraphTurnStreamer(
        responder_router=responder_router,
        router=router,
        planner=planner,
        embedder=embedder,
        db=db,
        search_tool=search_tool,
        http_client=http_client,
    )
    merged = await streamer.plan(state)

    parts: list[str] = []
    finish_reason = "stop"
    # Manage the stream by hand + close best-effort in ``finally`` (the responder's ``stream``
    # is typed ``AsyncIterator`` → ``contextlib.aclosing`` would not type-check).
    responder_stream = streamer.stream_response(merged)
    try:
        async for chunk in responder_stream:
            if chunk.content:
                parts.append(chunk.content)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            yield chunk
    finally:
        aclose = getattr(responder_stream, "aclose", None)
        if aclose is not None:
            await aclose()

    yield merged.model_copy(
        update={
            "response": "".join(parts),
            "finish_reason": finish_reason,
            "message_id": merged.message_id or uuid.uuid4().hex,
        }
    )
