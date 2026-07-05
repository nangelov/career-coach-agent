"""P2 **exit-criterion** end-to-end verification (plan.md P2 / tasks.md P2 ``(T)`` line).

P2's stated exit criterion is: *"chat history survives restart for accounts; vector insert +
similarity query verified"* — with the externally-added clause *"add extra weighting"*. The
individual building blocks are already unit/integration tested in isolation (P2-04 schema,
P2-06 embeddings + hybrid search in ``test_vector_search.py``, P2-07 persistence + rehydration
in ``test_chat_persistence.py`` / ``test_conversation_store.py``). This module is the
**phase-level integration proof** that ties them together end-to-end against **live Postgres**
and demonstrates the weighting behaviour explicitly. It does not re-implement or re-assert the
unit-level building blocks — it exercises them as a whole.

Two halves, matching the exit criterion:

* **Half 1 — restart → account chat history intact.** Drives a *multi-turn* logged-in
  conversation through the real :class:`~app.services.chat.ChatService` wired to the real
  :class:`~app.repositories.conversation_store.PostgresConversationStore` over live Postgres
  (the LLM is a scripted stub — no HF/token). A "restart" is simulated by discarding the
  in-memory session store (Redis key loss) and rebuilding the service; the proof is that a
  post-restart turn's model-visible context still contains the pre-restart turns (rehydrated
  from Postgres). This closes the gap in P2-07's ``test_restart_preserves_context_across_
  multiple_turns``, which proved the same at the **service layer with a fake store** — here it
  is proven against a **real database** *and* end-to-end through the ``POST /api/chat`` router.
  Guests are confirmed unaffected (no persisted history to lose — a restart simply resets
  their context, which is correct, not a regression).

* **Half 2 — vector insert + cosine similarity + weighting.** Inserts ``kb_chunks`` with
  constructed embeddings and proves (a) a *pure cosine* similarity query
  (``ORDER BY embedding <=> :q``) returns the expected nearest neighbour, and (b)
  :func:`~app.repositories.vector_search.hybrid_search_chunks`'s weight parameters
  *measurably* change the top-ranked result across four weight configurations, with the
  fixture's expected winner documented for each.

Like the other live-DB suites (``test_vector_search.py`` / ``test_conversation_store.py``),
this **skips cleanly** when Postgres / the migrated schema is unreachable, so free-tier CI
without a database stays green. The embeddings are controlled fakes (the real 8B model is
never loaded — see the injectable seam in ``test_embeddings.py``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.chat import get_chat_service
from app.config import settings
from app.llm.router import LLMRouter
from app.llm.types import StreamChunk
from app.main import app
from app.repositories.conversation_store import PostgresConversationStore
from app.repositories.models import KbChunk, KbDocument, User
from app.repositories.models.knowledge import EMBEDDING_DIM
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.vector_search import hybrid_search_chunks
from app.services.chat import ChatService
from app.services.session_memory import InMemorySessionMemory
from app.tools.base import ToolRegistry
from tests.fakes import FakeRegistry, FakeRouter

# --------------------------------------------------------------------------- #
# Live-Postgres gating (same skip-not-fail posture as the other integration suites)
# --------------------------------------------------------------------------- #


async def _postgres_reachable() -> bool:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - any connect failure → skip, never error the suite
        return False
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def provider() -> AsyncIterator[PostgresConnectionProvider]:
    """A real Postgres provider; skips if unreachable or the schema is not migrated."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(User).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("schema not migrated — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


@pytest_asyncio.fixture
async def user_id(provider: PostgresConnectionProvider) -> AsyncIterator[str]:
    """Create a throwaway user; delete it at the end (cascades away all it created)."""
    unique = uuid4().hex[:12]
    async with provider.session() as db:
        user = User(provider="google", sub=f"sub-{unique}", email=f"u-{unique}@example.com")
        db.add(user)
        await db.commit()
        uid = str(user.id)
    try:
        yield uid
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(uid))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session for read-only vector queries; skips if schema unreachable."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    engine = create_async_engine(settings.DATABASE_URL)
    conn = await engine.connect()
    trans = await conn.begin()
    db = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        try:
            await db.execute(select(KbDocument).limit(1))
        except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
            pytest.skip("knowledge schema not migrated — run `alembic upgrade head`")
        yield db
    finally:
        await db.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


def _service(router: FakeRouter, store: PostgresConversationStore) -> ChatService:
    """Build a real :class:`ChatService` over the scripted LLM + a FRESH in-memory session.

    A fresh :class:`InMemorySessionMemory` per service models a process restart / Redis key
    loss: nothing carries over in working memory, so a logged-in turn must rehydrate from
    Postgres. The scripted LLM / tool fakes (no HF, no token) live in ``tests.fakes``.
    """
    return ChatService(
        cast(LLMRouter, router),
        cast(ToolRegistry, FakeRegistry()),
        InMemorySessionMemory(),
        conversations=store,
    )


async def _drain(
    service: ChatService, session_id: str, message: str, *, user_id: str | None
) -> None:
    async for _ in service.stream_turn(session_id, message, user_id=user_id):
        pass


# --------------------------------------------------------------------------- #
# Half 1 — restart → account chat history intact (live Postgres)
# --------------------------------------------------------------------------- #


async def test_restart_preserves_account_history_multi_turn_live_postgres(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    """Multi-turn logged-in conversation survives a restart, proven against real Postgres.

    Two turns run pre-restart (persisted to Postgres). The service is then rebuilt with a
    fresh in-memory session store (Redis key loss) and drives two more turns. The proof: the
    **fourth** turn's model-visible context still contains the **first** turn's pair — so both
    the Postgres rehydration (turn 3) *and* the re-seed of the fresh working memory (so turn 4
    still sees pre-restart history) work against a live database. This is the live-DB, multi-
    turn analogue of P2-07's fake-store service test.
    """
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())

    # Pre-restart process: two turns, each persisted to Postgres.
    pre = _service(FakeRouter([[StreamChunk(content="A1", finish_reason="stop")]]), store)
    await _drain(pre, session_id, "Q1", user_id=user_id)
    pre = _service(FakeRouter([[StreamChunk(content="A2", finish_reason="stop")]]), store)
    await _drain(pre, session_id, "Q2", user_id=user_id)

    # "Restart": one fresh service (fresh working memory) drives both post-restart turns.
    router = FakeRouter(
        [
            [StreamChunk(content="A3", finish_reason="stop")],
            [StreamChunk(content="A4", finish_reason="stop")],
        ]
    )
    post = _service(router, store)
    await _drain(post, session_id, "Q3", user_id=user_id)  # rehydrates from Postgres + seeds
    await _drain(post, session_id, "Q4", user_id=user_id)  # reads the seeded working memory

    # Turn 3 saw the rehydrated pre-restart context.
    turn3 = [m.content for m in router.calls[0]]
    assert "Q1" in turn3 and "A1" in turn3 and "Q2" in turn3 and "A2" in turn3 and "Q3" in turn3
    # Turn 4 still sees turn 1 — the re-seed carried pre-restart history forward post-restart.
    turn4 = [m.content for m in router.calls[1]]
    assert "Q1" in turn4 and "A1" in turn4 and "A3" in turn4 and "Q4" in turn4


async def test_restart_preserves_account_history_via_router_path_live_postgres(
    provider: PostgresConnectionProvider, user_id: str
) -> None:
    """Same restart proof, but end-to-end through the real ``POST /api/chat`` router.

    Closes the "service-layer only" gap: the request goes through the FastAPI router, the SSE
    response is fully consumed (so the post-``done`` durable persist runs), the service is
    swapped for a fresh one (restart), and a second ``POST /api/chat`` for the same session +
    user rehydrates the first turn from Postgres. Asserted on the fresh service's recorded
    model call.
    """
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)

    async def post_turn(service: ChatService, message: str) -> None:
        app.dependency_overrides[get_chat_service] = lambda: service
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={"session_id": session_id, "message": message, "user_id": user_id},
                )
                assert resp.status_code == 200  # fully reads (drains) the SSE body
                assert "event: done" in resp.text
        finally:
            app.dependency_overrides.pop(get_chat_service, None)

    # Pre-restart turn through the router (persisted to Postgres).
    first = _service(FakeRouter([[StreamChunk(content="A1", finish_reason="stop")]]), store)
    await post_turn(first, "Q1")

    # Restart: brand-new service (fresh working memory), same session + user + store.
    restarted_router = FakeRouter([[StreamChunk(content="A2", finish_reason="stop")]])
    await post_turn(_service(restarted_router, store), "Q2")

    # The post-restart router turn rehydrated turn 1 from Postgres.
    contents = [m.content for m in restarted_router.calls[0]]
    assert "Q1" in contents and "A1" in contents and "Q2" in contents


async def test_guest_restart_has_no_history_live_postgres(
    provider: PostgresConnectionProvider,
) -> None:
    """A guest turn (no ``user_id``) persists nothing and rehydrates nothing after a restart.

    Confirms guests are unaffected by a restart *in the same way they always were*: there is no
    durable history to lose, so a restart simply resets their context — correct/expected, not a
    regression (design §4: "Guests get NO persisted history").
    """
    store = PostgresConversationStore(provider)
    session_id = str(uuid.uuid4())

    guest_router = FakeRouter([[StreamChunk(content="secret-answer", finish_reason="stop")]])
    pre = _service(guest_router, store)
    await _drain(pre, session_id, "guest-question", user_id=None)

    # Restart: fresh service. A guest turn on the same session sees no prior context.
    router = FakeRouter([[StreamChunk(content="ok", finish_reason="stop")]])
    post = _service(router, store)
    await _drain(post, session_id, "again", user_id=None)

    contents = [m.content for m in router.calls[0]]
    assert "guest-question" not in contents
    assert "secret-answer" not in contents


# --------------------------------------------------------------------------- #
# Half 2 — vector insert + cosine similarity + weighting (live Postgres)
# --------------------------------------------------------------------------- #


def _vec(components: dict[int, float]) -> list[float]:
    """A 4096-dim vector with the given ``{index: value}`` set, zeros elsewhere."""
    vec = [0.0] * EMBEDDING_DIM
    for index, value in components.items():
        vec[index] = value
    return vec


async def _add_chunk(
    session: AsyncSession, doc_id: uuid.UUID, index: int, content: str, embedding: list[float]
) -> uuid.UUID:
    chunk = KbChunk(
        kb_document_id=doc_id, chunk_index=index, content=content, embedding=embedding, meta={}
    )
    session.add(chunk)
    await session.flush()
    return chunk.id


async def test_pure_cosine_similarity_returns_expected_neighbor(session: AsyncSession) -> None:
    """Insert vectors; a pure ``ORDER BY embedding <=> :q`` returns the constructed neighbour.

    Fixture (query vector = a unit spike at index 20):

    * ``near``  — a near-duplicate of the query (spike at 20 + a tiny 0.1 at 21): cosine
      distance ≈ 0.005.
    * ``mid``   — a 45° vector (equal spikes at 20 and 5): cosine similarity ≈ 0.707,
      distance ≈ 0.293.
    * ``far``   — an orthogonal outlier (spike at 50): cosine distance = 1.0.

    The expected nearest neighbour is unambiguous by construction: ``near``. The query orders
    by the pgvector cosine-distance operator ``<=>`` (``KbChunk.embedding.cosine_distance``),
    i.e. the literal "insert + cosine similarity query on a vector column returns expected
    neighbor" acceptance bar.
    """
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()

    near_id = await _add_chunk(session, doc.id, 0, "near duplicate", _vec({20: 1.0, 21: 0.1}))
    mid_id = await _add_chunk(session, doc.id, 1, "forty-five degrees", _vec({20: 1.0, 5: 1.0}))
    far_id = await _add_chunk(session, doc.id, 2, "orthogonal outlier", _vec({50: 1.0}))

    query = _vec({20: 1.0})
    distance = KbChunk.embedding.cosine_distance(query)
    stmt = (
        select(KbChunk.id, distance.label("distance"))
        .where(KbChunk.kb_document_id == doc.id)
        .order_by(distance.asc())
    )
    ordered = [row.id for row in (await session.execute(stmt)).all()]

    # Nearest neighbour is the near-duplicate; full ordering is near → mid → far.
    assert ordered[0] == near_id
    assert ordered == [near_id, mid_id, far_id]


async def test_hybrid_search_weighting_changes_top_result_across_configs(
    session: AsyncSession,
) -> None:
    """The weight parameters measurably change the top result across four configurations.

    Two chunks are constructed so the two ranking signals disagree (as in P2-06's
    ``test_hybrid_search_weights_change_ranking``, extended here to sweep the blend):

    * ``lexical``  — content lexically matches the query word "kubernetes"; embedding is
      orthogonal to the query vector. Wins the **text** ranking, loses the **vector** ranking.
    * ``semantic`` — content is lexically unrelated to "kubernetes"; embedding **equals** the
      query vector (cosine distance 0). Wins the **vector** ranking, loses the **text** ranking.

    Sweeping four ``(vector_weight, text_weight)`` configurations and the documented winner of
    each — the crossover falls between config 2 and config 3, proving the weight is not a no-op:

    ======  ==================  ================  =========================================
    config  (vector, text)      expected winner   why
    ======  ==================  ================  =========================================
    1       (1.0, 0.0)          semantic          pure vector → the cosine-0 chunk
    2       (0.6, 0.4)          semantic          vector-leaning blend still favours vector
    3       (0.4, 0.6)          lexical           text-leaning blend flips to the lexical hit
    4       (0.0, 1.0)          lexical           pure lexical → the "kubernetes" text match
    ======  ==================  ================  =========================================

    (A symmetric ``0.5/0.5`` blend is intentionally avoided: with exactly two candidates whose
    ranks are mirror images, RRF ties them, so the *asymmetric* 0.6/0.4 and 0.4/0.6 blends give
    the deterministic, assertable crossover the proof needs.)
    """
    doc = KbDocument(title="doc", source_type="curated")
    session.add(doc)
    await session.flush()

    lexical_id = await _add_chunk(
        session,
        doc.id,
        0,
        "Kubernetes orchestrates containerized workloads at scale.",
        _vec({10: 1.0}),  # orthogonal to the query vector
    )
    semantic_id = await _add_chunk(
        session,
        doc.id,
        1,
        "Negotiating a fair salary during job interviews.",
        _vec({20: 1.0}),  # equals the query vector
    )

    query_text = "kubernetes"
    query_embedding = _vec({20: 1.0})

    async def top(vector_weight: float, text_weight: float) -> uuid.UUID:
        results = await hybrid_search_chunks(
            session,
            query_embedding=query_embedding,
            query_text=query_text,
            k=2,
            vector_weight=vector_weight,
            text_weight=text_weight,
            kb_document_ids=[doc.id],
        )
        return results[0].chunk_id

    # Four configs; the top result flips at the crossover between config 2 and config 3.
    assert await top(1.0, 0.0) == semantic_id
    assert await top(0.6, 0.4) == semantic_id
    assert await top(0.4, 0.6) == lexical_id
    assert await top(0.0, 1.0) == lexical_id
