"""Unit + integration tests for the pre-planner memory recall worker (P9-02, design §5.4).

Covers the acceptance criteria:

* a :class:`~app.memory.store.UserMemoryStore` (the reusable, ``BaseStore``-conforming adapter
  over ``user_memories``) embeds the turn and returns cosine top-k memories, and services a
  ``SearchOp`` while refusing the write ops that are the learn step's (P9-03),
* :func:`~app.agents.memory_agent.recall` populates ``MemoryContext.preferences`` +
  ``.memories`` for a logged-in user with data, and yields empty defaults for a user with none,
* a **guest** (``user_id is None``) gets an empty ``MemoryContext`` and never touches the DB,
* a simulated DB/embedding failure degrades to an empty ``MemoryContext`` (never raises), and
* the node adapter + an end-to-end run through the **real compiled graph** populate
  ``AgentState.memory`` before the planner.

Neither the real 8B embedder nor a live pgvector DB is used: an ``EmbeddingClient`` double
returns a fixed vector and a scripted async session/provider (``tests.fakes``) stands in.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

import pytest
from langgraph.store.base import GetOp, PutOp, SearchOp

from app.agents.graph import build_graph
from app.agents.memory_agent import _parse_user_uuid, make_memory_recall_node, recall
from app.agents.state import AgentState, Intent, MemoryContext, PlannerDecision
from app.memory.store import DEFAULT_MEMORY_K, UserMemoryStore, memory_namespace
from tests.fakes import (
    FakeDBProvider,
    FakeEmbeddingClient,
    FakeExecuteResult,
    FakeSession,
    user_memory_row,
)

_UID = str(uuid4())


def _state(message: str = "how do I grow?", *, user_id: str | None = _UID) -> AgentState:
    return AgentState(session_id="s", user_id=user_id, user_message=message)


def _prefs_then_memories(prefs: dict[str, Any], texts: list[str]) -> FakeSession:
    """A session scripted for one recall: the preferences read, then the memory search."""
    return FakeSession(
        [
            FakeExecuteResult([prefs] if prefs else []),
            FakeExecuteResult([user_memory_row(text=t) for t in texts]),
        ]
    )


# --------------------------------------------------------------------------- #
# UserMemoryStore — the reusable adapter
# --------------------------------------------------------------------------- #
async def test_store_search_embeds_turn_and_returns_topk() -> None:
    embedder = FakeEmbeddingClient(vector=[0.5, 0.25])
    session = FakeSession([FakeExecuteResult([user_memory_row(text="prefers bullet points")])])
    store = UserMemoryStore(embedder=embedder, db=FakeDBProvider(session))

    hits = await store.search_memories(uuid.UUID(_UID), "how do I grow?", k=3)

    assert embedder.queries == ["how do I grow?"]  # the turn was embedded as a query
    assert [h.text for h in hits] == ["prefers bullet points"]


async def test_store_blank_query_short_circuits() -> None:
    embedder = FakeEmbeddingClient()
    store = UserMemoryStore(embedder=embedder, db=FakeDBProvider(FakeSession([])))

    assert await store.search_memories(uuid.UUID(_UID), "   ") == []
    assert embedder.queries == []  # never embedded / searched


async def test_store_abatch_services_search_op() -> None:
    session = FakeSession([FakeExecuteResult([user_memory_row(text="based in Berlin")])])
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=FakeDBProvider(session))
    op = SearchOp(
        namespace_prefix=memory_namespace(_UID),
        filter=None,
        limit=5,
        offset=0,
        query="where am I based?",
        refresh_ttl=None,
    )

    (items,) = await store.abatch([op])

    assert len(items) == 1
    assert items[0].value["text"] == "based in Berlin"
    assert items[0].namespace == memory_namespace(_UID)


async def test_store_write_ops_and_sync_batch_are_unsupported() -> None:
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=FakeDBProvider(FakeSession([])))
    ns = memory_namespace(_UID)
    put = PutOp(namespace=ns, key="k", value={"text": "x"}, index=None, ttl=None)
    get = GetOp(namespace=ns, key="k", refresh_ttl=None)

    with pytest.raises(NotImplementedError):
        await store.abatch([put])
    with pytest.raises(NotImplementedError):
        await store.abatch([get])
    with pytest.raises(NotImplementedError):
        store.batch([get])


# --------------------------------------------------------------------------- #
# recall — prefs + memories populate for a logged-in user
# --------------------------------------------------------------------------- #
async def test_recall_populates_preferences_and_memories() -> None:
    prefs = {"tone": "friendly", "language": "en"}
    session = _prefs_then_memories(prefs, ["prefers bullet points", "targeting product mgmt"])
    db = FakeDBProvider(session)
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(), store=store, db=db)

    assert ctx.preferences == prefs
    assert ctx.memories == ["prefers bullet points", "targeting product mgmt"]


async def test_recall_empty_defaults_when_user_has_no_data() -> None:
    session = _prefs_then_memories({}, [])  # no preference row, no memories
    db = FakeDBProvider(session)
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(), store=store, db=db)

    assert ctx.preferences == {}
    assert ctx.memories == []


# --------------------------------------------------------------------------- #
# Guest — no durable recall, no DB access
# --------------------------------------------------------------------------- #
async def test_guest_gets_empty_context_without_touching_db() -> None:
    session = FakeSession([])  # any execute would raise "unexpected extra execute()"
    db = FakeDBProvider(session)
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(user_id=None), store=store, db=db)

    assert ctx == MemoryContext()
    assert session.statements == []  # never queried


async def test_guest_recall_reads_redis_personalization() -> None:
    # P9-07: a guest turn recalls its Redis-only, session-scoped personalization (not empty).
    from app.services.guest_memory import InMemoryGuestMemory

    guest_memory = InMemoryGuestMemory()
    await guest_memory.record(
        "s", memories=["prefers bullet points"], preferences={"tone": "concise"}
    )
    session = FakeSession([])  # the durable path must not be touched for a guest
    db = FakeDBProvider(session)
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(user_id=None), store=store, db=db, guest_memory=guest_memory)

    assert ctx.preferences == {"tone": "concise"}
    assert ctx.memories == ["prefers bullet points"]
    assert session.statements == []  # never queried Postgres


async def test_guest_recall_empty_without_guest_store() -> None:
    db = FakeDBProvider(FakeSession([]))
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(user_id=None), store=store, db=db, guest_memory=None)

    assert ctx == MemoryContext()


async def test_guest_recall_fails_soft_on_redis_error() -> None:
    class BoomGuestMemory:
        async def load(self, session_id: str) -> Any:
            raise RuntimeError("redis down")

        async def record(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - unused
            raise RuntimeError("redis down")

    ctx = await recall(_state(user_id=None), guest_memory=BoomGuestMemory())

    assert ctx == MemoryContext()  # degraded to empty, never raised


async def test_node_binds_guest_memory_without_db() -> None:
    # The guest path needs only the Redis store — no Postgres pool required to bind the node.
    from app.services.guest_memory import InMemoryGuestMemory

    guest_memory = InMemoryGuestMemory()
    await guest_memory.record("s", memories=["based in Berlin"])
    node = make_memory_recall_node(guest_memory=guest_memory)

    update = await node(_state(user_id=None))

    assert update["memory"].memories == ["based in Berlin"]


async def test_malformed_user_id_skips_recall() -> None:
    db = FakeDBProvider(FakeSession([]))
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(user_id="not-a-uuid"), store=store, db=db)

    assert ctx == MemoryContext()


def test_parse_user_uuid_variants() -> None:
    assert _parse_user_uuid(None) is None
    assert _parse_user_uuid("") is None
    assert _parse_user_uuid("not-a-uuid") is None
    valid = uuid4()
    assert _parse_user_uuid(str(valid)) == valid


# --------------------------------------------------------------------------- #
# Fail-soft on DB / embedding error
# --------------------------------------------------------------------------- #
async def test_recall_fails_soft_on_db_error() -> None:
    class BoomSession:
        statements: list[Any] = []

        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("db down")

    db = FakeDBProvider(BoomSession())
    store = UserMemoryStore(embedder=FakeEmbeddingClient(), db=db)

    ctx = await recall(_state(), store=store, db=db)

    assert ctx == MemoryContext()  # degraded to empty, never raised


async def test_recall_fails_soft_on_embedding_error() -> None:
    class BoomEmbedder(FakeEmbeddingClient):
        async def embed_query(self, text: str) -> list[float]:
            raise RuntimeError("embedder down")

    # Preferences read succeeds; the memory embedding blows up → whole context degrades to empty.
    session = FakeSession([FakeExecuteResult([{"tone": "friendly"}])])
    db = FakeDBProvider(session)
    store = UserMemoryStore(embedder=BoomEmbedder(), db=db)

    ctx = await recall(_state(), store=store, db=db)

    assert ctx == MemoryContext()


# --------------------------------------------------------------------------- #
# Node adapter (make_memory_recall_node → graph update shape)
# --------------------------------------------------------------------------- #
def test_node_without_db_is_noop() -> None:
    # The import-time default posture (no provider bound). It is intentionally **sync** so the
    # no-db module graph stays synchronously invokable (recall always runs).
    node = make_memory_recall_node()

    update = node(_state())

    assert update == {}  # leaves the default-empty MemoryContext in place


async def test_node_wraps_context_into_partial_update() -> None:
    prefs = {"tone": "concise"}
    db = FakeDBProvider(_prefs_then_memories(prefs, ["dislikes generic advice"]))
    node = make_memory_recall_node(embedder=FakeEmbeddingClient(), db=db)

    update = await node(_state())

    assert set(update) == {"memory"}
    ctx = update["memory"]
    assert ctx.preferences == prefs
    assert ctx.memories == ["dislikes generic advice"]


# --------------------------------------------------------------------------- #
# End-to-end through the real compiled graph (recall runs before the planner)
# --------------------------------------------------------------------------- #
def _planner_no_workers() -> Any:
    def planner(state: AgentState) -> dict[str, Any]:
        return {"plan": PlannerDecision(intent=Intent.CHAT, workers=[])}

    return planner


async def test_recall_runs_before_planner_end_to_end() -> None:
    prefs = {"formality": "casual"}
    db = FakeDBProvider(_prefs_then_memories(prefs, ["based in Berlin"]))
    compiled = build_graph(planner=_planner_no_workers(), embedder=FakeEmbeddingClient(), db=db)

    result = AgentState.model_validate(await compiled.ainvoke(_state("hi")))

    assert result.memory.preferences == prefs
    assert result.memory.memories == ["based in Berlin"]


async def test_guest_turn_recall_is_empty_end_to_end() -> None:
    # A guest turn must not crash and must leave memory empty; the DB is never queried.
    session = FakeSession([])
    compiled = build_graph(
        planner=_planner_no_workers(), embedder=FakeEmbeddingClient(), db=FakeDBProvider(session)
    )

    result = AgentState.model_validate(await compiled.ainvoke(_state("hi", user_id=None)))

    assert result.memory == MemoryContext()
    assert session.statements == []


def test_default_k_matches_design_topk() -> None:
    assert DEFAULT_MEMORY_K == 5
