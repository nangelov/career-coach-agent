"""Shared test doubles for the chat tool-call loop (single source of truth).

The chat-service unit/integration suites all drive :class:`~app.services.chat.ChatService`
with the same two fakes — a scripted LLM router and a canned tool registry. They used to be
re-declared near-verbatim in five modules (with subtle drift). They live here now so the
scripted-router / canned-registry contract has one home; import them from ``tests.fakes``.

Both intentionally satisfy their real counterparts *structurally* (duck typing) rather than
by subclassing, so callers pass them where an ``LLMRouter`` / ``ToolRegistry`` is expected
(with a ``cast`` or ``# type: ignore[arg-type]`` at the seam, as the suites already do).
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import httpx

from app.agents.state import AgentState, Citation, Intent, PlannerDecision
from app.llm.embeddings import EmbeddingClient
from app.llm.types import ChatMessage, CompletionResult, StreamChunk, ToolCall
from app.net.ssrf_guard import build_guarded_client
from app.repositories.vector_search import SearchResult
from app.schemas.auth import CurrentUser, SessionRole
from app.security.oidc import AuthorizationRequest, OIDCClient, OIDCUserInfo
from app.services.rate_limiting import InMemoryRateLimiter, RateLimitService
from app.tools.base import ToolResult

#: A scripted stream: a list of ``StreamChunk``s to yield, or an ``Exception`` to raise
#: when the stream is opened (models an all-models-failed / transport error).
Script = list[StreamChunk] | Exception


class FakeRouter:
    """A scripted :class:`~app.llm.router.LLMRouter` stand-in.

    Each :meth:`stream` call consumes the next scripted response and records the messages
    it was handed (in :attr:`calls`), so tests can assert what the model saw. Set
    ``always`` to replay a single script indefinitely (for the iteration-cap test).
    """

    def __init__(
        self, scripts: Sequence[Script] | None = None, *, always: Script | None = None
    ) -> None:
        self._scripts = list(scripts or [])
        self._always = always
        self.calls: list[list[ChatMessage]] = []

    async def stream(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[StreamChunk]:
        self.calls.append(list(messages))
        script = self._always if self._always is not None else self._scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for chunk in script:
            yield chunk

    async def aclose(self) -> None:
        pass


class FakeGraphRunner:
    """A scripted ``GraphTurnRunner`` stand-in for the graph-driven :class:`ChatService`.

    The P4 replacement for :class:`FakeRouter` + :class:`FakeRegistry` in the chat-service
    suites: the service no longer drives a raw LLM loop, it drives the multi-agent graph via
    the two-phase :meth:`plan` / :meth:`stream_response` seam.

    * :meth:`plan` records the input :class:`~app.agents.state.AgentState` (so a test can assert
      the session/user/history/user_message the turn built) and returns it with the scripted
      ``plan`` decision + ``citations`` folded in — the pre-responder merge the real
      :class:`~app.agents.graph.GraphTurnStreamer` produces.
    * :meth:`stream_response` consumes the next scripted stream (a list of ``StreamChunk``s to
      yield, or an ``Exception`` to raise) — the same ``scripts`` / ``always`` shape as
      :class:`FakeRouter`, so per-turn answers port over mechanically. Defaults to a single
      ``"Hello!"``/``stop`` turn when no scripts are given.

    ``plan_error`` raises from :meth:`plan` to exercise the service's terminal-error safety net
    (the real planner fails soft, so this is a synthetic infrastructure-failure probe).
    """

    def __init__(
        self,
        scripts: Sequence[list[StreamChunk] | Exception] | None = None,
        *,
        always: list[StreamChunk] | Exception | None = None,
        plan: PlannerDecision | None = None,
        citations: Sequence[Citation] | None = None,
        plan_error: Exception | None = None,
    ) -> None:
        default: list[list[StreamChunk] | Exception] = [
            [StreamChunk(content="Hello!", finish_reason="stop")]
        ]
        self._scripts = list(scripts) if scripts is not None else default
        self._always = always
        self._plan = plan if plan is not None else PlannerDecision(intent=Intent.CHAT)
        self._citations = list(citations) if citations is not None else []
        self._plan_error = plan_error
        #: The state handed to each :meth:`plan` call, in order (assert history / user_message).
        self.plan_states: list[AgentState] = []
        #: The merged state handed to each :meth:`stream_response` call, in order.
        self.stream_states: list[AgentState] = []
        self.closed = False

    async def plan(self, state: AgentState) -> AgentState:
        self.plan_states.append(state)
        if self._plan_error is not None:
            raise self._plan_error
        return state.model_copy(
            update={"plan": self._plan, "citations": list(self._citations), "response": "pre"}
        )

    def stream_response(self, state: AgentState) -> AsyncIterator[StreamChunk]:
        self.stream_states.append(state)
        script = self._always if self._always is not None else self._scripts.pop(0)
        return self._emit(script)

    async def _emit(self, script: list[StreamChunk] | Exception) -> AsyncIterator[StreamChunk]:
        if isinstance(script, Exception):
            raise script
        for chunk in script:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class FakeRegistry:
    """A minimal tool registry: one canned tool result per executed call.

    Records the calls it executed in :attr:`executed` so tests can assert the reassembled
    tool call reached the registry with merged arguments.
    """

    def __init__(self, result: str = '{"ok": true}') -> None:
        self._result = result
        self.executed: list[ToolCall] = []

    def schemas(self) -> list[dict[str, Any]]:
        return []

    async def execute(self, tool_call: ToolCall) -> ChatMessage:
        self.executed.append(tool_call)
        return ChatMessage(
            role="tool",
            content=self._result,
            name=tool_call.function.name,
            tool_call_id=tool_call.id,
        )


def fake_current_user(
    session_id: str, *, role: SessionRole = "guest", user_id: str | None = None
) -> CurrentUser:
    """Build a :class:`CurrentUser` for overriding ``require_auth`` in API tests.

    Mirrors what the real :class:`~app.services.auth.SessionAuthenticator` resolves from a
    verified token, so a test can stand in an authenticated caller without minting a JWT or
    seeding a session record.
    """
    return CurrentUser(session_id=session_id, role=role, user_id=user_id)


def unlimited_rate_limit_service() -> RateLimitService:
    """A :class:`RateLimitService` over an in-memory limiter with effectively no cap.

    For API tests that exercise a route *other* than the rate limit itself: overriding
    ``get_rate_limit_service`` with this keeps the real Redis wiring out of the test while
    never tripping the limit. Tests that assert limiting build a service with real caps.
    """
    huge = 10**9
    return RateLimitService(
        InMemoryRateLimiter(),
        guest_message_limit=huge,
        guest_upload_limit=huge,
        guest_window_seconds=3600,
        user_message_limit=huge,
        user_upload_limit=huge,
        user_window_seconds=3600,
    )


class FakeOIDCClient(OIDCClient):
    """A scripted :class:`~app.security.oidc.OIDCClient` stand-in (no network).

    :meth:`create_authorization_request` returns a deterministic request with a per-call
    distinct ``state`` (so multiple begins don't collide) and records what it was asked for;
    :meth:`exchange_code` returns the canned :class:`OIDCUserInfo` (with ``provider`` set to
    the exchanging provider) or raises the configured error. Both record their calls so
    tests can assert PKCE/state wiring.
    """

    def __init__(
        self,
        userinfo: OIDCUserInfo | None = None,
        *,
        exchange_error: Exception | None = None,
    ) -> None:
        self._userinfo = userinfo or OIDCUserInfo(
            provider="google", sub="sub-123", email="user@example.com", display_name="Test User"
        )
        self._exchange_error = exchange_error
        self._counter = 0
        self.authorization_requests: list[tuple[str, str]] = []
        self.exchanges: list[dict[str, str]] = []

    async def create_authorization_request(
        self, *, provider: str, redirect_uri: str
    ) -> AuthorizationRequest:
        self.authorization_requests.append((provider, redirect_uri))
        self._counter += 1
        state = f"state-{self._counter}"
        return AuthorizationRequest(
            url=f"https://provider.example/consent?provider={provider}&state={state}",
            state=state,
            code_verifier=f"verifier-{self._counter}",
            nonce=f"nonce-{self._counter}",
        )

    async def exchange_code(
        self, *, provider: str, redirect_uri: str, code: str, code_verifier: str
    ) -> OIDCUserInfo:
        self.exchanges.append(
            {
                "provider": provider,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": code_verifier,
            }
        )
        if self._exchange_error is not None:
            raise self._exchange_error
        return replace(self._userinfo, provider=provider)


# --------------------------------------------------------------------------- #
# RAG worker fakes (P4-04) — shared by test_rag_agent + test_agent_graph.
# The real 8B embedder and a live pgvector DB are never involved: an
# EmbeddingClient double returns a fixed vector, and a scripted async session /
# provider stands in for the pool so ``retrieve`` runs end-to-end offline.
# --------------------------------------------------------------------------- #
class FakeEmbeddingClient(EmbeddingClient):
    """Deterministic :class:`~app.llm.embeddings.EmbeddingClient` double.

    Records every ``embed_query`` text (so a test can assert the turn was embedded) and
    returns a fixed vector — no ``sentence-transformers`` / ``torch`` involved.
    """

    def __init__(self, vector: Sequence[float] | None = None) -> None:
        self._vector = list(vector) if vector is not None else [0.1] * 8
        self.queries: list[str] = []
        self.documents: list[list[str]] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.append(list(texts))
        return [list(self._vector) for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return list(self._vector)


class FakeExecuteResult:
    """Stand-in for a SQLAlchemy ``Result`` — serves ``.all()`` and ``.scalars().all()``."""

    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        """The single scalar row, or ``None`` — mirrors SQLAlchemy's existence-lookup helper."""
        return self._rows[0] if self._rows else None

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)


class _FakeScalarResult:
    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Async ``AsyncSession`` double: returns scripted results per ``execute`` call, in order.

    Ignores the statement (the SQL is exercised by the real integration tests); records the
    statements it saw so a test can inspect scoping if needed.
    """

    def __init__(self, results: Sequence[FakeExecuteResult]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> FakeExecuteResult:
        self.statements.append(statement)
        if not self._results:
            raise AssertionError("FakeSession: unexpected extra execute() call")
        return self._results.pop(0)


class FakeDBProvider:
    """:class:`~app.repositories.postgres.PostgresConnectionProvider` double.

    Its :meth:`session` async context manager yields the scripted :class:`FakeSession`, so a
    graph node can ``async with db.session() as session`` exactly as in production.
    """

    def __init__(self, session: Any) -> None:
        self.session_obj = session

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        yield self.session_obj


class FreshSessionDBProvider:
    """A :class:`~app.repositories.postgres.PostgresConnectionProvider` double that yields a
    **fresh** scripted :class:`FakeSession` per :meth:`session` call.

    Needed when two DB workers run concurrently in one graph turn (e.g. RAG + MARKET_INTEL):
    in production each ``async with db.session()`` acquires an independent pooled session, so a
    single shared :class:`FakeSession` (with a single consumed script) cannot model both. The
    factory builds an independent, identically-scripted session for each caller, so the two
    workers never contend for the same scripted results regardless of scheduling order.
    """

    def __init__(self, factory: Any) -> None:
        self._factory = factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        yield self._factory()


def market_and_rag_session(
    *,
    title: str = "rag-source",
    content: str = "rag grounding excerpt",
    canonical_role: str = "Data Scientist",
) -> FakeSession:
    """A scripted session that serves **both** the RAG and MARKET_INTEL worker read patterns.

    Both workers issue ``[id-scalars, hybrid-chunk-rows, title-rows]`` in that order; the market
    worker additionally reads ``role_profiles`` (scalars) as a 4th query. Scripting all four (the
    RAG worker simply leaves the 4th unused) lets one factory back either worker's fresh session.
    The chunk row carries ``meta.canonical_role`` so the market worker resolves its role profile.
    """
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    return FakeSession(
        [
            FakeExecuteResult([doc_id]),
            FakeExecuteResult(
                [
                    kb_chunk_row(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        content=content,
                        meta={"canonical_role": canonical_role},
                    )
                ]
            ),
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title=title)]),
            FakeExecuteResult(
                [SimpleNamespace(canonical_role=canonical_role, requirements={"Python": {}})]
            ),
        ]
    )


def kb_title_row(*, doc_id: uuid.UUID, title: str) -> SimpleNamespace:
    """A ``(kb_documents.id, kb_documents.title)`` row for the title-lookup query."""
    return SimpleNamespace(id=doc_id, title=title)


def kb_chunk_row(
    *,
    chunk_id: uuid.UUID,
    doc_id: uuid.UUID,
    content: str,
    score: float = 1.0,
    vector_similarity: float = 0.9,
    text_rank: float = 0.5,
    meta: dict[str, Any] | None = None,
) -> SimpleNamespace:
    """A row shaped like ``hybrid_search_chunks``'s RRF query output (real search over fakes)."""
    return SimpleNamespace(
        chunk_id=chunk_id,
        kb_document_id=doc_id,
        content=content,
        score=score,
        vector_similarity=vector_similarity,
        text_rank=text_rank,
        meta=meta or {},
    )


def user_memory_row(
    *,
    text: str,
    memory_id: uuid.UUID | None = None,
    similarity: float = 0.9,
    memory_type: str = "fact",
    confidence: float = 1.0,
) -> SimpleNamespace:
    """A row shaped like ``search_user_memories``'s cosine-search output (memory recall, P9)."""
    return SimpleNamespace(
        memory_id=memory_id or uuid.uuid4(),
        text=text,
        similarity=similarity,
        memory_type=memory_type,
        confidence=confidence,
    )


def make_search_result(
    *,
    chunk_id: uuid.UUID | None = None,
    doc_id: uuid.UUID | None = None,
    content: str = "excerpt",
    score: float = 1.0,
) -> SearchResult:
    """A :class:`~app.repositories.vector_search.SearchResult` for patched-search unit tests."""
    return SearchResult(
        chunk_id=chunk_id or uuid.uuid4(),
        kb_document_id=doc_id or uuid.uuid4(),
        content=content,
        score=score,
        vector_similarity=0.9,
        text_rank=0.5,
        meta={},
    )


# --------------------------------------------------------------------------- #
# Web Searcher worker fakes (P4-05) — shared by test_web_searcher + test_agent_graph.
# No real SearXNG / network: a scripted search tool returns a canned ToolResult and
# an httpx.MockTransport client serves crawl responses.
# --------------------------------------------------------------------------- #
class FakeSearchTool:
    """Structural ``SearchRunner`` double: returns a scripted ``internet_search`` result.

    Satisfies :class:`~app.agents.web_searcher.SearchRunner` by duck typing (only ``run`` is
    called). Records each call's arguments in :attr:`calls` so a test can assert the query the
    worker searched. Pass ``error`` to model a search-down / not-configured failure.
    """

    def __init__(
        self, results: Sequence[dict[str, str]] | None = None, *, error: str | None = None
    ) -> None:
        self._results = list(results) if results is not None else []
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        if self._error is not None:
            return ToolResult.error(self._error)
        return ToolResult.ok({"query": arguments.get("query"), "results": self._results})


def web_result(
    *,
    title: str = "Web result",
    url: str = "https://example.com/a",
    snippet: str = "a web snippet",
) -> dict[str, str]:
    """One ``internet_search`` result row (title/url/snippet) for the web-search fakes."""
    return {"title": title, "url": url, "snippet": snippet}


#: A fixed public IP every crawl-test host resolves to, so the SSRF guard treats the mock
#: hosts (``ex.com`` / ``example.com`` / …) as public and lets them through. SSRF-specific
#: rejection tests inject their own resolver mapping a host to a private/blocked address.
PUBLIC_TEST_IP = "93.184.216.34"


def public_resolver(_host: str) -> list[Any]:
    """A ``Resolver`` double: resolve any host to a single public IP (for crawl happy-paths)."""
    return [ipaddress.ip_address(PUBLIC_TEST_IP)]


def fake_crawl_client(
    pages: Mapping[str, str] | None = None,
    *,
    default_html: str = "<html><body><p>crawled page text</p></body></html>",
) -> httpx.AsyncClient:
    """An SSRF-**guarded** ``httpx.AsyncClient`` whose inner ``MockTransport`` serves canned HTML.

    ``pages`` maps a URL to its HTML body; unmapped URLs get ``default_html``. The MockTransport
    is wrapped by :func:`~app.net.ssrf_guard.build_guarded_client` with :func:`public_resolver`,
    so crawl tests exercise the real guard path (design §7.2) while no real network / DNS call is
    made (mirrors the ``internet_search`` tests' mock-transport pattern).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        html = (pages or {}).get(str(request.url), default_html)
        return httpx.Response(200, html=html)

    return build_guarded_client(
        inner_transport=httpx.MockTransport(handler), resolver=public_resolver
    )


class FakeResponderRouter:
    """A scripted :class:`~app.agents.responder.LLMResponder` stand-in (no HF).

    Serves both surfaces the responder uses: buffered :meth:`complete` and token-streamed
    :meth:`stream`. Records the messages it was handed on each call (:attr:`complete_messages`
    / :attr:`stream_messages`) so a test can assert the grounding material / persona / turn the
    responder built. Pass ``content`` for the buffered answer, ``chunks`` for the streamed token
    deltas (defaults to splitting ``content`` into two chunks), or ``error`` to model an
    all-models-failed failure on either surface.
    """

    def __init__(
        self,
        *,
        content: str = "Here is my grounded answer [1].",
        chunks: Sequence[StreamChunk] | None = None,
        error: Exception | None = None,
        finish_reason: str = "stop",
    ) -> None:
        self._content = content
        self._chunks = list(chunks) if chunks is not None else None
        self._error = error
        self._finish_reason = finish_reason
        self.complete_messages: list[list[ChatMessage]] = []
        self.stream_messages: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage], **_: Any) -> CompletionResult:
        self.complete_messages.append(list(messages))
        if self._error is not None:
            raise self._error
        return CompletionResult(
            content=self._content, finish_reason=self._finish_reason, model="fake"
        )

    async def stream(self, messages: Sequence[ChatMessage], **_: Any) -> AsyncIterator[StreamChunk]:
        self.stream_messages.append(list(messages))
        if self._error is not None:
            raise self._error
        if self._chunks is not None:
            for chunk in self._chunks:
                yield chunk
            return
        # Default: split the content into two deltas + a terminal finish-reason chunk.
        mid = max(1, len(self._content) // 2)
        yield StreamChunk(content=self._content[:mid])
        yield StreamChunk(content=self._content[mid:])
        yield StreamChunk(finish_reason=self._finish_reason)


def rag_db_one_hit(
    *, title: str = "rag-source", content: str = "rag grounding excerpt"
) -> tuple[FakeDBProvider, uuid.UUID, uuid.UUID]:
    """A :class:`FakeDBProvider` whose scripted session yields one KB hit end-to-end.

    Scripts the three reads ``retrieve`` issues in order — allowed document ids, the hybrid
    chunk rows (consumed by the real ``hybrid_search_chunks`` over the fake rows), and the
    parent-document titles — so a graph run through the real ``rag`` node produces one
    citation. Returns the provider plus the generated ``(doc_id, chunk_id)``.
    """
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    session = FakeSession(
        [
            FakeExecuteResult([doc_id]),
            FakeExecuteResult([kb_chunk_row(chunk_id=chunk_id, doc_id=doc_id, content=content)]),
            FakeExecuteResult([kb_title_row(doc_id=doc_id, title=title)]),
        ]
    )
    return FakeDBProvider(session), doc_id, chunk_id
