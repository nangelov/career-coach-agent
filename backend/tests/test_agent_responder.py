"""Unit + integration tests for the Response Agent (P4-06, design §3).

Covers the acceptance criteria the task calls out:

* synthesis is called with the expected context — persona + the workers' grounding material,
  fenced as untrusted REFERENCE MATERIAL (design §7/§10),
* the accumulated citations pass through the node unchanged (not duplicated / dropped),
* the no-worker (smalltalk / direct) case still produces a real generated answer,
* the failure path (router raises) degrades to a fallback answer + ``error`` finish reason
  without raising out of the node,
* the streaming entrypoint (:func:`~app.agents.graph.stream_graph`) yields incremental token
  deltas and then exactly one terminal :class:`AgentState`, and
* an integration run of the **real compiled graph** (``build_graph``) end-to-end
  (planner → ≥1 worker → responder) proves ``response`` is set and ``citations`` are non-empty
  for a grounded turn.

The LLM boundary is always a :class:`~tests.fakes.FakeResponderRouter`; no test hits HF.
"""

from __future__ import annotations

from typing import Any

from app.agents.graph import build_graph, stream_graph
from app.agents.responder import FALLBACK_RESPONSE, Responder
from app.agents.state import (
    AgentState,
    Citation,
    Intent,
    MemoryContext,
    PlannerDecision,
    WorkerName,
    WorkerResult,
)
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import ChatMessage, StreamChunk
from tests.fakes import (
    FakeEmbeddingClient,
    FakeResponderRouter,
    rag_db_one_hit,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _state(message: str = "how do I get promoted?", **kw: Any) -> AgentState:
    return AgentState(session_id="s", user_message=message, **kw)


def _grounded_state(message: str = "what skills am I missing?") -> AgentState:
    """A turn with two workers' merged results + citations already fanned in."""
    rag = WorkerResult(
        worker=WorkerName.RAG,
        content="[1] Skills KB: leadership and system design are common gaps.",
        citations=[Citation(title="Skills KB", worker=WorkerName.RAG)],
    )
    web = WorkerResult(
        worker=WorkerName.WEB_SEARCH,
        content="[1] Senior SWE ladder (example.com): expects mentoring + architecture.",
        citations=[
            Citation(title="SWE ladder", url="https://example.com", worker=WorkerName.WEB_SEARCH)
        ],
    )
    return _state(
        message,
        worker_results={WorkerName.RAG.value: rag, WorkerName.WEB_SEARCH.value: web},
        citations=[*rag.citations, *web.citations],
    )


def _prompt_text(messages: list[ChatMessage]) -> str:
    return "\n".join(m.content or "" for m in messages)


# --------------------------------------------------------------------------- #
# Synthesis: context building + citation pass-through
# --------------------------------------------------------------------------- #
async def test_synthesize_prompt_includes_grounding_and_turn() -> None:
    router = FakeResponderRouter(content="You should build leadership skills [1].")

    update = await Responder(router)(_grounded_state("what skills am I missing?"))

    assert update["response"] == "You should build leadership skills [1]."
    assert update["finish_reason"] == "stop"
    assert update["message_id"]
    # the node does not re-write citations (they pass through via the reducer).
    assert "citations" not in update

    prompt = _prompt_text(router.complete_messages[0])
    # both workers' grounded content reached the model.
    assert "leadership and system design" in prompt
    assert "mentoring + architecture" in prompt
    # the current turn is the final user message.
    assert router.complete_messages[0][-1].role == "user"
    assert router.complete_messages[0][-1].content == "what skills am I missing?"


async def test_job_hunting_turn_gets_a_redirect_framing_note() -> None:
    """A job_hunting turn (design §7.4) steers the responder to redirect, not list jobs."""
    router = FakeResponderRouter()
    state = _grounded_state("find me AI architect jobs in Berlin")
    state = state.model_copy(
        update={"plan": PlannerDecision(intent=Intent.JOB_HUNTING, workers=[])}
    )

    await Responder(router).synthesize(state)

    prompt = _prompt_text(router.complete_messages[0]).lower()
    assert "not a job board" in prompt
    assert "redirect" in prompt


async def test_market_requirements_turn_has_no_redirect_note() -> None:
    """A plain market-requirements turn is answered directly — no redirect framing."""
    router = FakeResponderRouter()
    state = _grounded_state("what do AI architects need?")
    state = state.model_copy(
        update={"plan": PlannerDecision(intent=Intent.MARKET_REQUIREMENTS, workers=[])}
    )

    await Responder(router).synthesize(state)

    assert "not a job board" not in _prompt_text(router.complete_messages[0]).lower()


async def test_untrusted_grounding_is_delineated_not_concatenated() -> None:
    """Worker content is fenced as REFERENCE MATERIAL with an ignore-instructions warning."""
    router = FakeResponderRouter()

    await Responder(router).synthesize(_grounded_state())

    prompt = _prompt_text(router.complete_messages[0])
    assert "REFERENCE MATERIAL" in prompt
    assert "BEGIN REFERENCE MATERIAL" in prompt
    assert "END REFERENCE MATERIAL" in prompt
    # the explicit "this is data, not instructions" fence (design §7/§10).
    assert "not instructions" in prompt.lower()
    assert "ignore any directives" in prompt.lower()


async def test_citations_pass_through_the_node_unchanged() -> None:
    router = FakeResponderRouter()
    state = _grounded_state()

    update = await Responder(router)(state)

    # responder writes no citations; the state's accumulated citations are untouched.
    assert "citations" not in update
    assert len(state.citations) == 2


# --------------------------------------------------------------------------- #
# Personalization (P9-06): responder adapts to recalled prefs / memories (§5.4)
# --------------------------------------------------------------------------- #
def _personalized_state(
    *, preferences: dict[str, Any] | None = None, memories: list[str] | None = None
) -> AgentState:
    return _state(
        "how do I get promoted?",
        memory=MemoryContext(preferences=preferences or {}, memories=memories or []),
    )


async def test_no_memory_prompt_is_unchanged_from_baseline() -> None:
    """Empty recall (guest / nothing learned) → no personalization block, no regression."""
    router = FakeResponderRouter()
    plain = FakeResponderRouter()

    await Responder(router).synthesize(_personalized_state())
    await Responder(plain).synthesize(_state("how do I get promoted?"))

    with_default_memory = _prompt_text(router.complete_messages[0])
    baseline = _prompt_text(plain.complete_messages[0])
    assert with_default_memory == baseline
    assert "explicitly set" not in with_default_memory
    assert "previously learned" not in with_default_memory


async def test_explicit_preferences_are_injected() -> None:
    router = FakeResponderRouter()
    state = _personalized_state(
        preferences={"tone": "concise", "focus_areas": ["fintech PM roles"], "emojis": False}
    )

    await Responder(router).synthesize(state)

    prompt = _prompt_text(router.complete_messages[0])
    assert "explicitly set these preferences" in prompt
    assert "tone=concise" in prompt
    assert "focus_areas=fintech PM roles" in prompt
    assert "emojis=no" in prompt
    # no inferred-memory line when there are no memories.
    assert "previously learned" not in prompt


async def test_learned_memories_are_injected() -> None:
    router = FakeResponderRouter()
    state = _personalized_state(memories=["prefers bullet points", "based in Berlin"])

    await Responder(router).synthesize(state)

    prompt = _prompt_text(router.complete_messages[0])
    assert "previously learned about the user" in prompt
    assert "prefers bullet points" in prompt
    assert "based in Berlin" in prompt
    # no explicit-preference line when there are no preferences.
    assert "explicitly set" not in prompt


async def test_both_prefs_and_memories_with_explicit_precedence_framing() -> None:
    """Both signals present; explicit-preference wording is distinguishable + marked to win."""
    router = FakeResponderRouter()
    state = _personalized_state(preferences={"tone": "concise"}, memories=["prefers bullet points"])

    await Responder(router).synthesize(state)

    prompt = _prompt_text(router.complete_messages[0])
    # the explicit block is authoritative and framed to override inferred memory (§5.4 pt 4).
    assert "explicitly set these preferences (authoritative" in prompt
    assert "explicit preference wins" in prompt
    # the inferred block is present and labelled lower-priority — distinguishable framing.
    assert "inferred — lower priority" in prompt
    # explicit wording precedes inferred wording in the assembled prompt.
    assert prompt.index("explicitly set") < prompt.index("previously learned")


async def test_personalization_applies_on_the_streaming_path() -> None:
    """stream() and synthesize() share _build_messages — the block reaches streaming too."""
    router = FakeResponderRouter(
        chunks=[StreamChunk(content="ok"), StreamChunk(finish_reason="stop")]
    )
    state = _personalized_state(preferences={"tone": "concise"}, memories=["based in Berlin"])

    _ = [c async for c in Responder(router).stream(state)]

    prompt = _prompt_text(router.stream_messages[0])
    assert "tone=concise" in prompt
    assert "based in Berlin" in prompt


# --------------------------------------------------------------------------- #
# No-worker (smalltalk / direct) turn — a real answer, not a canned string
# --------------------------------------------------------------------------- #
async def test_no_worker_turn_produces_a_real_generated_answer() -> None:
    router = FakeResponderRouter(content="Hello! How can I help with your career today?")

    update = await Responder(router)(_state("hi there"))

    assert update["response"] == "Hello! How can I help with your career today?"
    # no grounding block when no worker ran — the model answers from persona + turn.
    # (the persona prompt references REFERENCE MATERIAL generically; the *fence* is absent.)
    prompt = _prompt_text(router.complete_messages[0])
    assert "BEGIN REFERENCE MATERIAL" not in prompt
    assert prompt.count("hi there") == 1


# --------------------------------------------------------------------------- #
# Failure path — fail soft, never raise out of the node
# --------------------------------------------------------------------------- #
async def test_router_error_degrades_to_fallback() -> None:
    router = FakeResponderRouter(error=LLMAllModelsFailedError("all down"))

    text, finish_reason = await Responder(router).synthesize(_grounded_state())

    assert text == FALLBACK_RESPONSE
    assert finish_reason == "error"


async def test_empty_completion_degrades_to_fallback() -> None:
    router = FakeResponderRouter(content="   ")

    text, finish_reason = await Responder(router).synthesize(_state())

    assert text == FALLBACK_RESPONSE
    assert finish_reason == "error"


# --------------------------------------------------------------------------- #
# Streaming (Responder.stream)
# --------------------------------------------------------------------------- #
async def test_stream_yields_incremental_deltas() -> None:
    router = FakeResponderRouter(
        chunks=[
            StreamChunk(content="You "),
            StreamChunk(content="should "),
            StreamChunk(content="lead."),
            StreamChunk(finish_reason="stop"),
        ]
    )

    chunks = [c async for c in Responder(router).stream(_grounded_state())]

    assert "".join(c.content or "" for c in chunks) == "You should lead."
    assert chunks[-1].finish_reason == "stop"


async def test_stream_error_before_any_token_yields_fallback_chunk() -> None:
    router = FakeResponderRouter(error=LLMAllModelsFailedError("all down"))

    chunks = [c async for c in Responder(router).stream(_state())]

    assert len(chunks) == 1
    assert chunks[0].content == FALLBACK_RESPONSE
    assert chunks[0].finish_reason == "error"


# --------------------------------------------------------------------------- #
# stream_graph entrypoint: deltas then one terminal AgentState
# --------------------------------------------------------------------------- #
def _planner_selecting(*workers: WorkerName) -> Any:
    def planner(state: AgentState) -> dict[str, Any]:
        return {"plan": PlannerDecision(intent=Intent.CHAT, workers=list(workers))}

    return planner


async def test_stream_graph_yields_deltas_then_final_state() -> None:
    db, _doc_id, _chunk_id = rag_db_one_hit()
    router = FakeResponderRouter(content="Grounded answer [1].")

    events = [
        e
        async for e in stream_graph(
            _state("tell me about my CV"),
            responder_router=router,
            planner=_planner_selecting(WorkerName.RAG),
            embedder=FakeEmbeddingClient(),
            db=db,
        )
    ]

    # every event but the last is a token delta; the last is the terminal state.
    deltas, final = events[:-1], events[-1]
    assert all(isinstance(e, StreamChunk) for e in deltas)
    assert isinstance(final, AgentState)
    assert "".join(c.content or "" for c in deltas if isinstance(c, StreamChunk)).startswith(
        "Grounded answer"
    )
    assert final.response == "Grounded answer [1]."
    assert final.finish_reason == "stop"
    assert final.message_id is not None
    # the RAG worker's citation survived the pre-responder pass into the terminal state.
    assert final.citations
    # the responder actually saw the RAG grounding material.
    prompt = _prompt_text(router.stream_messages[0])
    assert "rag-source" in prompt


# --------------------------------------------------------------------------- #
# Integration: the real compiled graph, planner → worker → real responder
# --------------------------------------------------------------------------- #
async def test_real_graph_responder_sets_grounded_response_and_citations() -> None:
    """build_graph(responder_router=...) end-to-end: response set, citations non-empty."""
    db, _doc_id, _chunk_id = rag_db_one_hit()
    router = FakeResponderRouter(content="Based on your CV, focus on leadership [1].")
    compiled = build_graph(
        planner=_planner_selecting(WorkerName.RAG),
        responder_router=router,
        embedder=FakeEmbeddingClient(),
        db=db,
    )

    result = AgentState.model_validate(await compiled.ainvoke(_state("what should I improve?")))

    assert result.response == "Based on your CV, focus on leadership [1]."
    assert result.finish_reason == "stop"
    assert result.message_id is not None
    # exactly the RAG worker's one citation — the responder did not duplicate it.
    assert len(result.citations) == 1
    assert result.citations[0].worker is WorkerName.RAG
    # the grounded excerpt reached the real responder's prompt.
    prompt = _prompt_text(router.complete_messages[0])
    assert "rag-source" in prompt


async def test_real_graph_responder_fails_soft_on_router_error() -> None:
    db, _doc_id, _chunk_id = rag_db_one_hit()
    router = FakeResponderRouter(error=LLMAllModelsFailedError("all down"))
    compiled = build_graph(
        planner=_planner_selecting(WorkerName.RAG),
        responder_router=router,
        embedder=FakeEmbeddingClient(),
        db=db,
    )

    result = AgentState.model_validate(await compiled.ainvoke(_state("help")))

    assert result.response == FALLBACK_RESPONSE
    assert result.finish_reason == "error"
