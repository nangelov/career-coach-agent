"""API smoke test for ``POST /api/chat`` (P1-04, extended with P3-04 auth/rate-limit, and the
P4-07 graph-driven end-to-end integration).

Overrides the :func:`~app.api.chat.get_chat_service` dependency with a fake service that
yields canned events, plus ``require_auth`` (authenticated caller) and
``get_rate_limit_service`` (in-memory, uncapped), so the real LLM router / Redis / HF wiring
never runs. Asserts the endpoint returns a valid ``text/event-stream`` with correctly framed
SSE events.

The final test wires a **real** :class:`~app.services.chat.ChatService` over a **real**
:class:`~app.agents.graph.GraphTurnStreamer` (compiled multi-agent graph) with only the
outermost collaborators faked (responder/planner routing, embedder, DB) — no live HF or
Postgres — to prove the P4 exit criterion end-to-end: a worker-routed turn streams tokens
**and** returns citations through the actual ``POST /api/chat`` flow.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
from httpx import ASGITransport

from app.agents.graph import GraphTurnStreamer
from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from app.api.chat import get_chat_service
from app.llm.types import ChatMessage
from app.main import app
from app.schemas.chat import ChatEvent, DoneEvent, StartEvent, TokenEvent
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory
from tests.fakes import (
    FakeEmbeddingClient,
    FakeResponderRouter,
    fake_current_user,
    rag_db_one_hit,
    unlimited_rate_limit_service,
)


class _FakeService:
    async def stream_turn(
        self,
        session_id: str,
        message: str,
        *,
        history: Sequence[ChatMessage] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        yield StartEvent(message_id="m1")
        yield TokenEvent(content="Hi")
        yield DoneEvent(message_id="m1", finish_reason="stop")


async def test_chat_endpoint_streams_sse() -> None:
    app.dependency_overrides[get_chat_service] = lambda: _FakeService()
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: start" in body
    assert "event: token" in body
    assert '"content": "Hi"' in body
    assert "event: done" in body


async def test_chat_endpoint_rejects_empty_message() -> None:
    # With an authenticated caller, body validation is what must reject the empty message.
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/chat", json={"session_id": "s1", "message": ""})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


async def test_chat_endpoint_requires_auth() -> None:
    # No Authorization header and no override → the auth guard rejects before streaming.
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 401


def _planner_selecting(*workers: WorkerName) -> object:
    """A stub planner node routing to exactly ``workers`` (drives routing through the graph)."""

    def planner(state: AgentState) -> dict[str, object]:
        return {"plan": PlannerDecision(intent=Intent.CV_QUESTION, workers=list(workers))}

    return planner


async def test_worker_routed_turn_streams_tokens_and_cites_end_to_end() -> None:
    """P4 exit criterion: a worker-routed turn streams tokens AND cites sources.

    Drives the **real** compiled graph (guardrails → recall → planner → RAG worker → responder)
    end-to-end through ``POST /api/chat`` with only the outer collaborators faked — a scripted
    responder router, a fake embedder, and a scripted DB standing in for pgvector — so the RAG
    worker retrieves a real citation and the responder streams a grounded answer. No live HF,
    no live Postgres.
    """
    db, _doc_id, _chunk_id = rag_db_one_hit(title="rag-source")
    streamer = GraphTurnStreamer(
        responder_router=FakeResponderRouter(content="Based on your CV, focus on leadership [1]."),
        planner=_planner_selecting(WorkerName.RAG),  # type: ignore[arg-type]
        embedder=FakeEmbeddingClient(),
        db=db,
    )
    service = ChatService(streamer, InMemorySessionMemory())

    app.dependency_overrides[get_chat_service] = lambda: service
    app.dependency_overrides[require_auth] = lambda: fake_current_user("s1")
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/chat", json={"session_id": "s1", "message": "what should I improve?"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.text
    # The plan (which worker ran) is surfaced before the answer streams.
    assert "event: plan" in body
    assert '"rag"' in body
    # Tokens streamed, and the terminal done event carries the RAG worker's citation.
    assert "event: token" in body
    assert "event: done" in body
    assert "rag-source" in body
