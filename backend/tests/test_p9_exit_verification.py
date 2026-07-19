"""P9 phase-exit verification (P9-10) — the teachable-memory / feedback loop, end to end.

A **verification-only** module (no product code changed): it ties every prior P9 building block
together and drives them as one story, proving the plan.md P9 exit criterion:

    "across two sessions the assistant adapts to a stated preference; a 👎 changes future
     behaviour; the user can inspect & delete what was learned."

The prior per-task suites each prove a *piece* in isolation (``test_memory_learn`` — the learn
core over fakes; ``test_memory_agent`` — recall over a scripted session; ``test_memory_api`` — the
CRUD router over an in-memory fake; ``test_memory_gdpr_filter`` — the PII/Art. 9 gate; the
``*_persistence`` suites — each real primitive against Postgres). **This** module proves they
*compose* across the whole chain over the **same** ``user_memories`` / ``preferences`` tables, so
there is no hidden drift between the write path (learn), the read path (recall), the panel
(CRUD API), and the responder's adaptation.

Posture. Unlike the fully-offline P8-06 module, the P9 chain's whole point is that the learn
*write*, the recall *read*, and the CRUD *delete* all address the **same durable rows** — proving
that with fakes would be proving a shared dict, not a shared table. So points 1–5 run against
**live Postgres** (the ``vector(4096)`` + FK schema SQLite cannot represent), faking only the true
external edges (the 8B embedder → a fixed 4096-dim vector, and the extractor LLM → a scripted
candidate list). They **skip cleanly** when Postgres is unreachable, exactly like the sibling
``*_persistence`` suites, and run under ``make test-integration``. Point 6 (retention) reuses the
same live finder; points 7–8 (frontend wiring + cross-task consistency) are pure source scans that
always run.

Coverage of the P9-10 task's eight points (see per-test docstrings):

1. **Cross-session adaptation** — turn 1 drives the real ``run_learn_from_turn`` (learn wiring);
   turn 2 drives the **compiled graph** for the same user and the real recall surfaces what was
   learned, and the responder's assembled messages reflect it (P9-06).
2. **A 👎 changes future behaviour** — a real down-vote demotes/removes the attributed memory and
   learns an "avoid X" preference; a subsequent recall no longer surfaces the removed memory but
   does surface the new preference.
3. **Inspect + delete** — ``GET /api/memory`` reflects what ``run_learn_from_turn`` actually wrote;
   ``DELETE /api/memory/{id}`` removes one; a later ``GET`` and a later recall both no longer see
   it (same table).
4. **PII/GDPR gate under the full loop** — a contact detail is redacted and an Art. 9 statement is
   dropped, confirmed via ``GET /api/memory``'s response.
5. **Guest → account upgrade** — a guest's Redis personalization migrates and is visible via
   ``GET /api/memory`` post-upgrade, through the same PII/Art. 9 gate.
6. **Retention purge spares live users** — the real stale-user finder purges a stale fixture user
   and excludes a freshly-active one.
7. **Frontend wiring** — the memory panel + feedback clients hit exactly the endpoints the backend
   exposes (source scan of ``lib/memory.ts`` / ``lib/messageFeedback.ts``).
8. **Cross-task consistency** — the PII/Art. 9 gate, the "list a user's memories" query, and the
   dedup/confidence logic each live in exactly one place and are reused, not duplicated.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.graph import NodeUpdate, PlannerNode, stream_graph
from app.agents.state import AgentState, Intent, PlannerDecision
from app.api.memory import get_memory_service
from app.config import settings
from app.llm.embeddings import EmbeddingClient
from app.main import app
from app.memory.guest_personalization import GuestPersonalizationMigrator
from app.memory.learn import MemoryCandidate, run_learn_from_turn
from app.memory.store import UserMemoryStore
from app.repositories.message_feedback_store import PostgresMessageFeedbackStore
from app.repositories.models.identity import Conversation, Message, Session, User
from app.repositories.models.knowledge import EMBEDDING_DIM, UserMemory
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.preference_store import PostgresPreferenceStore
from app.repositories.retention import PostgresRetentionRepository
from app.security.dependencies import require_auth
from app.services.guest_memory import InMemoryGuestMemory
from app.services.memory import MemoryService
from app.tasks.retention_purge import run_retention_purge
from tests.fakes import FakeResponderRouter, fake_current_user

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
_APP_ROOT = Path(__file__).resolve().parents[1] / "app"


# =========================================================================== #
# Live-DB harness (mirrors test_memory_learn_persistence / test_retention_*).  #
# =========================================================================== #
class _FixedEmbedder(EmbeddingClient):
    """Embedder returning a **non-zero** constant 4096-dim vector (matches the real column).

    Non-zero on purpose: pgvector cosine distance is NaN for a zero vector, so a shared non-zero
    constant makes every embedding identical → cosine similarity 1.0. That deterministically
    exercises the dedup branch and makes recall's top-k return whatever the user actually has —
    exactly what a composition proof needs (the 8B model itself is out of scope here).
    """

    def __init__(self, value: float = 0.1) -> None:
        self._value = value

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[self._value] * EMBEDDING_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [self._value] * EMBEDDING_DIM


class _StaticExtractor:
    """A :class:`~app.memory.learn.MemoryExtractor` double returning a fixed candidate list."""

    def __init__(self, candidates: list[MemoryCandidate]) -> None:
        self._candidates = candidates

    async def propose(self, *, user_text: str, assistant_text: str) -> list[MemoryCandidate]:
        return list(self._candidates)


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
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — integration test skipped")
    prov = PostgresConnectionProvider.from_settings(settings)
    try:
        async with prov.session() as db:
            await db.execute(select(UserMemory).limit(1))
    except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
        await prov.aclose()
        pytest.skip("knowledge schema not applied — run `alembic upgrade head`")
    try:
        yield prov
    finally:
        await prov.aclose()


class _Seed:
    def __init__(self, user_id: str, session_id: str, message_id: str) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.message_id = message_id


@pytest_asyncio.fixture
async def seed(provider: PostgresConnectionProvider) -> AsyncIterator[_Seed]:
    """Seed user → session → conversation → assistant message; delete the user at the end.

    The single assistant message doubles as the turn a feedback/thumb-down attaches to (real FK)
    **and** as recent activity (so this user is 'fresh' for the retention check). Deleting the user
    at teardown cascades away its memories/feedback/messages (GDPR cascade, §4)."""
    unique = uuid4().hex[:12]
    session_id = str(uuid.uuid4())
    message_id = uuid4().hex
    async with provider.session() as db:
        user = User(provider="google", sub=f"sub-{unique}", email=f"u-{unique}@example.com")
        db.add(user)
        await db.flush()
        db.add(Session(id=session_id, user_id=user.id))
        conversation = Conversation(session_id=session_id, user_id=user.id)
        db.add(conversation)
        await db.flush()
        db.add(
            Message(
                conversation_id=conversation.id,
                message_id=message_id,
                role="assistant",
                content="Some advice.",
            )
        )
        uid = str(user.id)
        await db.commit()
    try:
        yield _Seed(uid, session_id, message_id)
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(uid))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def wire_memory_api(
    provider: PostgresConnectionProvider,
) -> Iterator[Callable[[_Seed], MemoryService]]:
    """Point ``/api/memory`` at a **real** Postgres-backed service + a chosen caller; clean up.

    The service composes the real ``PostgresPreferenceStore`` and the real ``UserMemoryStore``
    (embedder faked) over the same ``provider`` the learn/recall paths use — so the panel reads and
    deletes exactly the rows the learn step wrote (no separate data path)."""

    def _as(seed: _Seed) -> MemoryService:
        service = MemoryService(
            preferences=PostgresPreferenceStore.from_provider(provider),
            memories=UserMemoryStore(embedder=_FixedEmbedder(), db=provider),
        )
        user = fake_current_user(seed.session_id, role="user", user_id=seed.user_id)
        app.dependency_overrides[get_memory_service] = lambda: service
        app.dependency_overrides[require_auth] = lambda: user
        return service

    yield _as
    app.dependency_overrides.clear()


def _planner_chat() -> PlannerNode:
    """A planner seam selecting a direct CHAT turn (no workers → straight to the responder)."""

    def planner(state: AgentState) -> NodeUpdate:
        return {"plan": PlannerDecision(intent=Intent.CHAT, workers=[])}

    return planner


def _system_prompt_text(messages: Sequence[object]) -> str:
    """Concatenate the ``system`` message contents the responder was handed (for assertions)."""
    parts: list[str] = []
    for m in messages:
        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if role == "system" and isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


# =========================================================================== #
# 1. Cross-session adaptation — learn (session 1) → recall + responder (session 2). #
# =========================================================================== #
async def test_p9_cross_session_adaptation_end_to_end(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    """Session 1 learns a stated preference; session 2 (a **separate** turn through the compiled
    graph) recalls it and the responder adapts to it — a genuine round trip over one real table.

    Session 1: the real ``run_learn_from_turn`` (fake extractor + real store/feedback) writes the
    memory to ``user_memories``. Session 2: ``stream_graph`` runs the real compiled graph
    (input guardrail → **real recall over the same Postgres** → planner seam → real responder) for
    the same user; the terminal state's ``memory.memories`` surfaces the learned fact, and the
    responder's assembled system prompt carries it (P9-06 personalization)."""
    learned = "prefers concise bullet-point answers"
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)
    feedback = PostgresMessageFeedbackStore.from_provider(provider)

    # --- Session 1: learn -------------------------------------------------------------------- #
    first = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="please keep answers short and in bullets",
        assistant_text="Sure — I'll keep it tight.",
        store=store,
        extractor=_StaticExtractor(
            [MemoryCandidate(text=learned, memory_type="style", confidence=0.9)]
        ),
        feedback=feedback,
    )
    assert len(first.inserted) == 1  # genuinely persisted to user_memories

    # --- Session 2: a separate turn through the compiled graph ------------------------------- #
    router = FakeResponderRouter(content="Here's the plan.")
    state = AgentState(
        session_id=str(uuid.uuid4()),  # a *different* session — cross-session by construction
        user_id=seed.user_id,
        user_message="help me plan my week",
    )
    events = [
        e
        async for e in stream_graph(
            state,
            responder_router=router,
            planner=_planner_chat(),
            embedder=_FixedEmbedder(),
            db=provider,
        )
    ]
    final = events[-1]
    assert isinstance(final, AgentState)

    # Recall surfaced what session 1 learned (real read of the row the learn write created).
    assert learned in final.memory.memories
    # And the responder's assembled prompt reflects it (P9-06 adaptation), framed as trusted.
    system_text = _system_prompt_text(router.stream_messages[0])
    assert learned in system_text


# =========================================================================== #
# 2. A 👎 changes future behaviour (demote/remove + learn an "avoid X").         #
# =========================================================================== #
async def test_p9_downvote_changes_future_behavior(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    """A real thumb-down removes the memory attributed to the bad turn and learns an explicit
    negative preference; a **subsequent** recall no longer surfaces the removed memory but does
    surface the new "avoid X" preference — the §5.5 behaviour change, proven over the real table."""
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)
    feedback = PostgresMessageFeedbackStore.from_provider(provider)
    bad_memory = "recommended generic networking advice"

    # A memory learned from the turn, at a confidence one demotion drives to the floor (→ removed).
    memory_id = await store.add_memory(
        uuid.UUID(seed.user_id),
        bad_memory,
        memory_type="fact",
        confidence=0.3,
        source_message_id=seed.message_id,
    )
    # The user thumbs the turn down with a reason.
    recorded = await feedback.record(
        message_id=seed.message_id,
        rating="down",
        reason="too generic",
        user_id=seed.user_id,
        session_id=seed.session_id,
    )
    assert recorded is not None

    result = await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="that wasn't useful",
        assistant_text="generic advice",
        store=store,
        extractor=_StaticExtractor([]),
        feedback=feedback,
    )
    assert result.removed == [memory_id]  # 0.3 - 0.3 ≤ floor → removed

    # A subsequent recall (session 2) no longer surfaces the removed memory, but does surface the
    # newly-learned explicit "avoid" preference.
    recalled = await store.search_memories(uuid.UUID(seed.user_id), "any next turn", k=10)
    texts = [hit.text for hit in recalled]
    assert all(bad_memory not in t for t in texts)
    assert any("too generic" in t for t in texts)


# =========================================================================== #
# 3. Inspect + delete — GET reflects learn's writes; DELETE removes from the same table. #
# =========================================================================== #
async def test_p9_inspect_and_delete_memories_end_to_end(
    provider: PostgresConnectionProvider,
    seed: _Seed,
    client: httpx.AsyncClient,
    wire_memory_api: Callable[[_Seed], MemoryService],
) -> None:
    """``GET /api/memory`` reflects exactly what ``run_learn_from_turn`` wrote; ``DELETE`` removes
    one; a later ``GET`` and a later recall both no longer see it — proving the CRUD delete and the
    recall read share one underlying table, not two data paths that could drift."""
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)
    feedback = PostgresMessageFeedbackStore.from_provider(provider)
    # Two candidates of different memory_types so neither dedups the other (fixed-embedding sim=1.0
    # only collapses same-type near-duplicates).
    await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="I'm aiming for a staff engineer role, based in Berlin",
        assistant_text="Noted.",
        store=store,
        extractor=_StaticExtractor(
            [
                MemoryCandidate(
                    text="targeting a staff engineer role", memory_type="preference", confidence=0.8
                ),
                MemoryCandidate(text="based in Berlin", memory_type="fact", confidence=0.8),
            ]
        ),
        feedback=feedback,
    )

    wire_memory_api(seed)

    # GET reflects the two learned memories (embeddings never on the wire).
    listed = (await client.get("/api/memory")).json()["memories"]
    texts = {m["text"] for m in listed}
    assert {"targeting a staff engineer role", "based in Berlin"} <= texts
    assert all("embedding" not in m for m in listed)

    # Delete one → 204; a later GET no longer lists it.
    target = next(m for m in listed if m["text"] == "based in Berlin")
    assert (await client.delete(f"/api/memory/{target['id']}")).status_code == 204
    remaining = (await client.get("/api/memory")).json()["memories"]
    assert {m["text"] for m in remaining} == {"targeting a staff engineer role"}

    # The delete is gone from what recall would read next turn too (same table, no parallel path).
    recalled = await store.search_memories(uuid.UUID(seed.user_id), "next turn", k=10)
    assert all("based in Berlin" not in hit.text for hit in recalled)


# =========================================================================== #
# 4. PII/GDPR gate holds under the full loop (confirmed via GET /api/memory).    #
# =========================================================================== #
async def test_p9_pii_gdpr_gate_holds_end_to_end(
    provider: PostgresConnectionProvider,
    seed: _Seed,
    client: httpx.AsyncClient,
    wire_memory_api: Callable[[_Seed], MemoryService],
) -> None:
    """A turn whose candidates carry a contact detail and an Art. 9 (health) statement, run through
    the **real** learn pipeline, yields ``user_memories`` that are PII-redacted and never carry the
    special-category content — confirmed via the panel's ``GET /api/memory`` response."""
    store = UserMemoryStore(embedder=_FixedEmbedder(), db=provider)
    feedback = PostgresMessageFeedbackStore.from_provider(provider)
    await run_learn_from_turn(
        user_id=seed.user_id,
        message_id=seed.message_id,
        user_text="context",
        assistant_text="ok",
        store=store,
        extractor=_StaticExtractor(
            [
                MemoryCandidate(
                    text="reach the user at john@example.com to schedule",
                    memory_type="fact",
                    confidence=0.8,
                ),
                MemoryCandidate(
                    text="the user has diabetes and manages it daily",
                    memory_type="fact",
                    confidence=0.8,
                ),
                MemoryCandidate(
                    text="targeting a product management role",
                    memory_type="preference",
                    confidence=0.8,
                ),
            ]
        ),
        feedback=feedback,
    )

    wire_memory_api(seed)
    listed = (await client.get("/api/memory")).json()["memories"]
    texts = [m["text"] for m in listed]

    # The contact PII is redacted (kept, minus the email); the Art. 9 statement was dropped
    # entirely; the benign preference survives.
    assert all("@example.com" not in t for t in texts)
    assert any("[EMAIL REDACTED]" in t for t in texts)
    assert all("diabetes" not in t for t in texts)
    assert "targeting a product management role" in texts


# =========================================================================== #
# 5. Guest → account upgrade carries personalization (through the same gate).    #
# =========================================================================== #
async def test_p9_guest_upgrade_carries_personalization(
    provider: PostgresConnectionProvider,
    seed: _Seed,
    client: httpx.AsyncClient,
    wire_memory_api: Callable[[_Seed], MemoryService],
) -> None:
    """A guest accumulates Redis-only personalization; on upgrade the migrator persists it durably
    (re-gated), and it is visible via ``GET /api/memory`` — with the Art. 9 item dropped on the way
    in (defense-in-depth), proving the gate holds on the migration path too."""
    guest_memory = InMemoryGuestMemory()
    guest_session = "guest-" + uuid4().hex
    await guest_memory.record(
        guest_session,
        memories=["prefers concise walkthroughs", "the user is managing depression"],
        preferences={"tone": "direct"},
    )

    migrator = GuestPersonalizationMigrator(
        guest_memory=guest_memory,
        preferences=PostgresPreferenceStore.from_provider(provider),
        memories=UserMemoryStore(embedder=_FixedEmbedder(), db=provider),
    )
    await migrator.migrate(guest_session_id=guest_session, user_id=seed.user_id)

    wire_memory_api(seed)
    body = (await client.get("/api/memory")).json()
    texts = [m["text"] for m in body["memories"]]

    assert body["preferences"]["tone"] == "direct"  # explicit preference migrated
    assert "prefers concise walkthroughs" in texts  # benign memory migrated
    assert all("depression" not in t for t in texts)  # Art. 9 dropped on migration


# =========================================================================== #
# 6. Retention purge spares a freshly-active user, purges only the stale one.    #
# =========================================================================== #
class _CapturingEraser:
    """A :class:`~app.tasks.retention_purge.UserEraser` double — records ids, deletes nothing.

    Lets the purge core prove *selection* (which users it targets) without actually cascading a
    delete, so the shared DB / the fresh seed user is never mutated by this check."""

    def __init__(self) -> None:
        self.erased: list[str] = []

    async def delete_user(self, user_id: str) -> None:
        self.erased.append(user_id)


async def test_p9_retention_purge_spares_fresh_active_user(
    provider: PostgresConnectionProvider, seed: _Seed
) -> None:
    """The real stale-user finder (P9-08) selects a stale fixture user and excludes the freshly
    active seed user (whose only message was created just now via this same P9 loop)."""
    now = datetime.now(UTC)
    # A stale throwaway user: account 200 days old, last message 45 days ago (> the 30-day window).
    async with provider.session() as db:
        stale_user = User(
            provider="google",
            sub=f"sub-{uuid4().hex[:12]}",
            email=f"stale-{uuid4().hex[:8]}@example.com",
            created_at=now - timedelta(days=200),
        )
        db.add(stale_user)
        await db.flush()
        stale_id = str(stale_user.id)
        stale_session = uuid4().hex
        db.add(Session(id=stale_session, user_id=stale_user.id))
        conv = Conversation(session_id=stale_session, user_id=stale_user.id)
        db.add(conv)
        await db.flush()
        db.add(
            Message(
                conversation_id=conv.id,
                message_id=uuid4().hex,
                role="user",
                content="hello",
                created_at=now - timedelta(days=45),
            )
        )
        await db.commit()

    eraser = _CapturingEraser()
    try:
        summary = await run_retention_purge(
            finder=PostgresRetentionRepository.from_provider(provider),
            eraser=eraser,
            retention_days=30,
            now=now,
        )
        assert summary["failed"] == 0
        assert stale_id in eraser.erased  # stale user selected for purge
        assert seed.user_id not in eraser.erased  # freshly-active user spared
    finally:
        async with provider.session() as db:
            existing = await db.get(User, uuid.UUID(stale_id))
            if existing is not None:
                await db.delete(existing)
                await db.commit()


# =========================================================================== #
# 7. Frontend wiring — the panel + feedback clients hit the backend's routes.    #
# =========================================================================== #
def test_p9_frontend_clients_target_the_backend_endpoints() -> None:
    """Source scan (mirrors the P7/P8 contract scans): the P9-09 clients call exactly the paths the
    backend exposes — ``/api/memory`` (GET/PUT prefs/DELETE one/DELETE all) and
    ``/api/messages/{id}/feedback`` (POST) — so the frontend and backend contracts line up."""
    memory = (_FRONTEND / "lib" / "memory.ts").read_text(encoding="utf-8")
    assert "`${baseUrl}/api/memory`" in memory  # GET + DELETE-all
    assert "`${baseUrl}/api/memory/preferences`" in memory  # PUT preferences
    assert "`${baseUrl}/api/memory/${encodeURIComponent(memoryId)}`" in memory  # DELETE one
    assert 'method: "PUT"' in memory and 'method: "DELETE"' in memory

    feedback = (_FRONTEND / "lib" / "messageFeedback.ts").read_text(encoding="utf-8")
    assert "`${baseUrl}/api/messages/${encodeURIComponent(messageId)}/feedback`" in feedback
    assert 'method: "POST"' in feedback

    # The backend really serves those prefixes (guards against a silent frontend/back drift).
    assert 'prefix="/api/memory"' in (_APP_ROOT / "api" / "memory.py").read_text(encoding="utf-8")
    assert 'prefix="/api/messages"' in (_APP_ROOT / "api" / "message_feedback.py").read_text(
        encoding="utf-8"
    )


# =========================================================================== #
# 8. Cross-task consistency — one home per shared primitive, reused not copied.   #
# =========================================================================== #
def test_p9_pii_gate_and_memory_primitives_are_not_duplicated() -> None:
    """Guards point 8: the PII/Art. 9 gate, the "list a user's memories" query, and the
    dedup/confidence logic each live in exactly one place and are **reused** — no drift a later
    change could desync. A duplicated copy is a gap for the owning task, flagged not silently fixed.
    """
    # (a) The Art. 9 classifier lives only in gdpr_filter; the write-boundary gate only in learn.
    special_defs = [
        p
        for p in _APP_ROOT.rglob("*.py")
        if "def special_category_of(" in p.read_text(encoding="utf-8")
    ]
    assert special_defs == [_APP_ROOT / "memory" / "gdpr_filter.py"]
    gate_defs = [
        p for p in _APP_ROOT.rglob("*.py") if "def gate_candidate(" in p.read_text(encoding="utf-8")
    ]
    assert gate_defs == [_APP_ROOT / "memory" / "learn.py"]

    # The guest personalization paths *reuse* the same gate (import it) rather than re-implementing.
    guest = (_APP_ROOT / "memory" / "guest_personalization.py").read_text(encoding="utf-8")
    assert "gate_candidate" in guest and "from app.memory.learn import" in guest
    assert "def special_category_of" not in guest and "def gate_candidate" not in guest

    # (b) The panel "list a user's memories" query has one home (the repository primitive).
    list_defs = [
        p
        for p in _APP_ROOT.rglob("*.py")
        if "def list_user_memories(" in p.read_text(encoding="utf-8")
    ]
    assert list_defs == [_APP_ROOT / "repositories" / "vector_search.py"]

    # (c) The dedup + confidence-clamp logic has one home (the learn core); the guest learner, which
    # deliberately skips dedup, does not re-implement it.
    for symbol in ("def _near_duplicate(", "def _clamp_confidence("):
        homes = [p for p in _APP_ROOT.rglob("*.py") if symbol in p.read_text(encoding="utf-8")]
        assert homes == [_APP_ROOT / "memory" / "learn.py"], f"{symbol} must live only in learn.py"
    assert "_near_duplicate" not in guest  # guest learner does not duplicate dedup
