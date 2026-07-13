"""P6 phase-exit verification (P6-09) — the market-intelligence chain, end to end.

This is a **verification-only** module (no product code changed): it ties the P6 building
blocks together and drives them through the **real** mining pipeline, the **real**
:class:`~app.services.roles.RolesService` + ``GET /api/roles/...`` router, the **real**
compiled multi-agent graph + :class:`~app.services.chat.ChatService`, and the **real** market
repositories, proving the one plan.md P6 exit criterion as a single story:

    "For a target role, the app returns cited, frequency-ranked market requirements and a
    skills gap; extraction happens once per role, reused across users. No job listings are
    ever shown; a job-hunting turn is redirected, not answered with listings."

The prior per-task suites (``test_market_agent`` / ``test_roles_service`` / ``test_roles_api``
/ ``test_skills_gap`` / ``test_topic_guardrail`` / ``test_learning_resources``) prove each
piece in isolation with fakes on *both* sides of a seam; **this** module proves they *compose*
— mining actually populates the row the requirements API reads back, the cache actually spares
the second user a re-mine, and the graph has **no** path that serialises a job posting.

Only the true external edges are faked, mirroring the P4-10 / P5-08 posture ("real stack,
in-memory/fake ports, no external creds / live HF / live Tavily"): the requirement-extraction
LLM, the Tavily search pool, the crawl HTTP transport, and the in-process embedder. The two
authoritative live-Postgres proofs (mining → requirements → gap round-trip, and the
learning-resource JSONB lookup) run against docker-compose Postgres and **skip cleanly** when
no DB is reachable.

Coverage of the P6-09 task's six points:

1. **mining → cited, frequency-ranked requirements** — ``test_live_mining_then_requirements_*``
   (authoritative, live DB) + ``test_worker_only_returns_role_profile_content`` (offline seam).
2. **skills gap** — ``test_live_mining_then_requirements_then_gap`` (live DB).
3. **cache reuse (second user, no re-extraction)** — ``test_second_request_served_from_cache_*``
   (real endpoint + real service; spies prove the DB/resolver/enqueue are hit once).
4. **topic guardrail redirect, not listings** — ``test_job_hunting_turn_is_redirected_*`` +
   ``test_off_topic_turn_short_circuits_*`` (real graph) + the worker structural check.
5. **no job listings anywhere** — ``test_no_job_listing_surface_in_backend_api`` +
   ``test_no_job_listing_surface_in_frontend``.
6. **learning-resource corpus queryable** — ``test_live_learning_resource_corpus_is_queryable``
   (live DB) + ``test_learning_resource_lookup_is_wired`` (offline seam).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.graph import OFF_TOPIC_REFUSAL, GraphTurnStreamer
from app.agents.market_agent import (
    EXTRACTION_TOOL_NAME,
    mine_role_requirements,
    resolve_canonical_role,
    retrieve_market_intel,
)
from app.agents.planner import PLANNER_TOOL_NAME
from app.agents.state import AgentState, WorkerName
from app.api.roles import get_roles_service
from app.config import settings
from app.ingestion.profile import ProfileSchema
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall, ToolSchema
from app.main import app
from app.repositories.kb_kinds import TAXONOMY_KIND
from app.repositories.learning_resources import LEARNING_RESOURCE_KIND, list_resources_for_skill
from app.repositories.models.knowledge import EMBEDDING_DIM, KbDocument
from app.repositories.models.market import JobPosting, RoleProfile
from app.repositories.postgres import PostgresConnectionProvider
from app.repositories.vector_search import add_kb_chunk
from app.schemas.chat import ChatEvent, DoneEvent, ErrorEvent, TokenEvent
from app.security.dependencies import (
    get_rate_limit_service,
    require_auth,
    resolve_optional_user,
)
from app.services.chat import ChatService
from app.services.profile_store import InMemoryProfileStore
from app.services.roles import RoleProfileCache, RolesService
from app.services.session_memory import InMemorySessionMemory
from app.services.skills_gap import SkillsGapService
from tests.fakes import (
    FakeEmbeddingClient,
    FakeResponderRouter,
    FakeSearchTool,
    FreshSessionDBProvider,
    fake_crawl_client,
    fake_current_user,
    market_and_rag_session,
    unlimited_rate_limit_service,
)


# =========================================================================== #
# Shared test doubles (edges only — the pipeline in between is real).         #
# =========================================================================== #
class _ScriptedExtractor:
    """A scripted requirement-extraction ``LLMCompleter``: forces ``record_requirements``.

    Returns the next scripted skill list per posting as a native tool call — no free-text
    parsing — so the **real** :func:`~app.agents.market_agent._extract_requirements` fence +
    tool-choice path runs over it (the only faked edge is the model itself).
    """

    def __init__(self, skills_per_call: Sequence[Sequence[str]]) -> None:
        self._skills = [list(s) for s in skills_per_call]

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        skills = self._skills.pop(0) if self._skills else []
        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    function=FunctionCall(
                        name=EXTRACTION_TOOL_NAME, arguments=json.dumps({"skills": skills})
                    ),
                )
            ],
            model="fake",
        )


class _PlannerCompleter:
    """A scripted planner ``LLMCompleter`` forcing ``record_plan`` with a fixed intent (§7.4)."""

    def __init__(self, intent: str) -> None:
        self._intent = intent

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        args = json.dumps({"intent": self._intent, "steps": ["handle the turn"]})
        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(id="c1", function=FunctionCall(name=PLANNER_TOOL_NAME, arguments=args))
            ],
            finish_reason="tool_calls",
            model="fake",
        )


class _PermissiveRobots:
    async def can_fetch(self, url: str) -> bool:
        return True


class _NoWaitLimiter:
    async def acquire(self, url: str) -> None:
        return None


class _FixedEmbedder:
    """Embedder returning a fixed, non-degenerate ``vector(4096)`` per text (matches the column)."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] * EMBEDDING_DIM for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1] * EMBEDDING_DIM


class _FakeCache(RoleProfileCache):
    """An in-memory stand-in for the Redis role-requirements response cache."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.sets = 0

    async def get(self, role_key: str) -> str | None:
        return self.store.get(role_key)

    async def set(self, role_key: str, payload: str, *, ttl_seconds: int) -> None:
        self.store[role_key] = payload
        self.sets += 1


class _SpyResolver:
    """Records how many times canonicalization ran (the DB-touching taxonomy resolve)."""

    def __init__(self, canonical: str) -> None:
        self.canonical = canonical
        self.calls = 0

    async def __call__(self, role: str) -> str:
        self.calls += 1
        return self.canonical


class _RecordingEnqueuer:
    """A mining-enqueue spy: records each ``target_role`` but never runs Celery/crawl."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *, target_role: str) -> str:
        self.calls.append(target_role)
        return f"mine-{len(self.calls)}"


class _CountingDB:
    """A DB provider double counting ``session()`` calls; scripts one role-profile read."""

    def __init__(self, profile: RoleProfile | None) -> None:
        self._profile = profile
        self.sessions = 0

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        self.sessions += 1
        from tests.fakes import FakeExecuteResult, FakeSession

        rows = [self._profile] if self._profile is not None else []
        yield FakeSession([FakeExecuteResult(rows)])


class _StubSkillsGap:
    async def compute(self, user_id: str, role: str) -> Any:  # pragma: no cover - unused here
        raise AssertionError("gap not exercised in the requirements-cache tests")


def _role_profile(canonical: str) -> RoleProfile:
    return RoleProfile(
        canonical_role=canonical,
        requirements={
            "Python": {"frequency": 0.9, "weight": 2.0, "evidence": ["https://ex.com/p1"]},
            "SQL": {"frequency": 0.4, "weight": 1.0, "evidence": ["https://ex.com/p2"]},
        },
        evidence_count=5,
        refreshed_at=datetime.now(UTC),
    )


def _requirements_service(
    *,
    cache: _FakeCache,
    resolver: _SpyResolver,
    enqueuer: _RecordingEnqueuer,
    db: Any,
) -> RolesService:
    return RolesService(
        cache=cache,
        resolve_canonical=resolver,
        enqueue_mine=enqueuer,
        skills_gap=_StubSkillsGap(),  # type: ignore[arg-type]
        db=db,
        stale_after_seconds=10_000,
        cache_ttl_seconds=3600,
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _collect(service: ChatService, session: str, message: str) -> list[ChatEvent]:
    return [event async for event in service.stream_turn(session, message)]


# =========================================================================== #
# 3. Cache reuse — "second user hits the cache, no re-extraction".            #
#    Drives the REAL RolesService through the REAL endpoint twice; spies      #
#    prove the second call touched neither Postgres, the canonicalizer, nor   #
#    the mining enqueue — extraction happens once per role, reused for all.   #
# =========================================================================== #
async def test_second_request_served_from_cache_no_reextraction(
    client: httpx.AsyncClient,
) -> None:
    cache, resolver, enqueuer = _FakeCache(), _SpyResolver("Data Scientist"), _RecordingEnqueuer()
    db = _CountingDB(_role_profile("Data Scientist"))
    service = _requirements_service(cache=cache, resolver=resolver, enqueuer=enqueuer, db=db)

    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[resolve_optional_user] = lambda: None
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        first = await client.get("/api/roles/data%20scientist/requirements")
        second = await client.get("/api/roles/data%20scientist/requirements")  # a "second user"
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    body = first.json()
    # Cited + frequency-ranked (Python 0.9 before SQL 0.4), not a bare skill list.
    assert [r["skill"] for r in body["requirements"]] == ["Python", "SQL"]
    assert body["requirements"][0]["evidence"] == ["https://ex.com/p1"]
    assert body["evidence_count"] == 5

    assert second.status_code == 200
    assert second.json()["requirements"][0]["skill"] == "Python"
    # The crux: the second request re-ran NOTHING expensive — one DB read, one canonicalize,
    # zero mines. Extraction is paid once per role and amortised across users (§5.6).
    assert db.sessions == 1
    assert resolver.calls == 1
    assert enqueuer.calls == []


async def test_cold_role_enqueues_a_single_mine_never_runs_it_inline(
    client: httpx.AsyncClient,
) -> None:
    """A never-mined role returns 202 + a poll handle and enqueues exactly one background mine —
    no crawl/extraction runs on the request path (§7.5)."""
    cache, resolver, enqueuer = _FakeCache(), _SpyResolver("Rare Role"), _RecordingEnqueuer()
    db = _CountingDB(None)  # no role_profiles row → cold
    service = _requirements_service(cache=cache, resolver=resolver, enqueuer=enqueuer, db=db)

    app.dependency_overrides[get_roles_service] = lambda: service
    app.dependency_overrides[resolve_optional_user] = lambda: None
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
    try:
        response = await client.get("/api/roles/rare%20role/requirements")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["task_id"] == "mine-1"
    assert enqueuer.calls == ["Rare Role"]  # one mine, enqueued (not run inline)
    assert cache.sets == 0  # a 202 carries no requirements — nothing cached


# =========================================================================== #
# 4. Topic guardrail — redirect, not listings.                               #
# =========================================================================== #
async def test_job_hunting_turn_is_redirected_through_the_real_graph() -> None:
    """A ``JOB_HUNTING`` turn runs the real graph → market worker (reads the cached corpus) →
    responder, and returns a **market-requirements redirect** — never a listing.

    The responder's grounding is the role-requirement summary the market worker surfaced; the
    turn is *not* short-circuited (unlike off-topic) — it is redirected by the responder (§7.4).
    """
    market_summary = (
        "Market requirements for AI Solution Architect: Python named in 80% of postings."
    )
    db = FreshSessionDBProvider(
        lambda: market_and_rag_session(
            content=market_summary, canonical_role="AI Solution Architect", title="Market: AISA"
        )
    )
    responder = FakeResponderRouter(content="Rather than listings, here is what the market wants.")
    streamer = GraphTurnStreamer(
        responder_router=responder,
        router=_PlannerCompleter("job_hunting"),
        embedder=FakeEmbeddingClient(),
        db=db,
    )
    service = ChatService(streamer, InMemorySessionMemory())

    events = await _collect(service, "s1", "find me AI architect jobs in Berlin")

    assert not any(isinstance(e, ErrorEvent) for e in events)
    tokens = "".join(e.content for e in events if isinstance(e, TokenEvent))
    assert tokens == "Rather than listings, here is what the market wants."
    assert isinstance(events[-1], DoneEvent)
    # The responder DID run (redirect, not a short-circuit refusal)…
    assert responder.stream_messages != []
    # …and what it was grounded on is the role-requirements summary — not job listings.
    grounding = "\n".join(m.content or "" for m in responder.stream_messages[0])
    assert "Market requirements" in grounding
    assert "Python" in grounding


async def test_off_topic_turn_short_circuits_with_no_worker_or_llm_call() -> None:
    """An ``OFF_TOPIC`` turn (e.g. "is this rash serious?") short-circuits to the canned refusal
    with **no** worker or responder LLM call (P6-04 routing)."""

    class _BoomDB:
        """Proves no worker ran: any DB session use raises."""

        @asynccontextmanager
        async def session(self) -> AsyncIterator[Any]:
            raise AssertionError("no worker should run for an off-topic turn")
            yield  # pragma: no cover

    responder = FakeResponderRouter()  # spy: must never be called
    streamer = GraphTurnStreamer(
        responder_router=responder,
        router=_PlannerCompleter("off_topic"),
        embedder=FakeEmbeddingClient(),
        db=_BoomDB(),
    )
    service = ChatService(streamer, InMemorySessionMemory())

    events = await _collect(service, "s1", "is this rash serious?")

    assert not any(isinstance(e, ErrorEvent) for e in events)
    tokens = "".join(e.content for e in events if isinstance(e, TokenEvent))
    assert tokens == OFF_TOPIC_REFUSAL
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].finish_reason == "off_topic"
    # Neither the responder LLM nor any worker was invoked.
    assert responder.stream_messages == []
    assert responder.complete_messages == []


async def test_worker_only_returns_role_profile_content_never_listings() -> None:
    """The request-path MARKET_INTEL worker only ever returns ``role_profiles``-derived
    requirement content — there is no field/path by which a ``job_postings`` row reaches a chat
    response (design §5.6 / §1.1)."""
    db = FreshSessionDBProvider(
        lambda: market_and_rag_session(
            content="Market requirements for X: Python.", canonical_role="X"
        )
    )
    result = await retrieve_market_intel(
        AgentState(session_id="s", user_message="what does role X require?"),
        embedder=FakeEmbeddingClient(),
        db=db,
    )

    assert result.worker is WorkerName.MARKET_INTEL
    # The worker's structured payload carries requirement data keyed by role — and *only* that.
    assert set(result.data) == {"chunk_count", "role_profiles"}
    assert "X" in result.data["role_profiles"]
    # No listing/posting/apply concept anywhere in the returned data keys.
    serialised = json.dumps(result.data).lower()
    assert "job_posting" not in serialised
    assert "apply" not in serialised


# =========================================================================== #
# 5. No job listings are ever shown anywhere (backend API + frontend).        #
# =========================================================================== #
_FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_no_job_listing_surface_in_backend_api() -> None:
    """The whole backend API surface exposes the market roles routes and the generic job-status
    poller — but **no** job-listings route (``GET/POST /api/jobs``), re-verified across the phase.
    """
    paths = set(app.openapi()["paths"])

    # The market surface that replaces v1 job-search exists…
    assert "/api/roles/{role}/requirements" in paths
    assert "/api/roles/{role}/gap" in paths

    # …and the ONLY ``/api/jobs`` route is the generic async-task status poller (P5-06) — no
    # listings / apply / save / track endpoint anywhere.
    jobs_paths = {p for p in paths if p.startswith("/api/jobs")}
    assert jobs_paths == {"/api/jobs/status/{task_id}"}


def test_no_job_listing_surface_in_frontend() -> None:
    """The frontend has no job-listings UI: no code references a ``/api/jobs`` route other than
    the generic status poller, and no save/track/apply-to-job client call (design §1.1)."""
    if not _FRONTEND_ROOT.is_dir():  # pragma: no cover - frontend always present in the repo
        pytest.skip("frontend/ not present")

    offending: list[str] = []
    for path in [
        *(_FRONTEND_ROOT / "components").glob("*.tsx"),
        *(_FRONTEND_ROOT / "lib").glob("*.ts"),
    ]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("*") or stripped.startswith("//"):
                continue  # a doc comment (e.g. "not a job board") — not a code path
            # A /api/jobs reference that is NOT the generic status poller would be a listings call.
            if "/api/jobs/" in line and "/api/jobs/status/" not in line:
                offending.append(f"{path.name}:{lineno}: {stripped}")
            if any(tok in line for tok in ("saveJob", "trackJob", "applyToJob")):
                offending.append(f"{path.name}:{lineno}: {stripped}")

    assert offending == [], f"unexpected job-listings surface in frontend: {offending}"


# =========================================================================== #
# 6. Learning-resource corpus is queryable (offline seam).                    #
# =========================================================================== #
async def test_learning_resource_lookup_is_wired() -> None:
    """The skill-keyed learning-resource read (P6-06) is wired end-to-end over a session — the
    corpus is queryable, not write-only. (The live test below proves the real JSONB containment.)
    """
    from tests.fakes import FakeExecuteResult, FakeSession

    doc = KbDocument(
        title="Deep Learning Specialization",
        source=f"{LEARNING_RESOURCE_KIND}:https://coursera.org/dl",
        source_type="curated",
        user_id=None,
        content="A course covering Python and TensorFlow.",
        meta={"kind": LEARNING_RESOURCE_KIND, "skill_keys": ["python"]},
    )
    session = FakeSession([FakeExecuteResult([doc])])

    resources = await list_resources_for_skill(session, "Python")  # type: ignore[arg-type]

    assert [r.title for r in resources] == ["Deep Learning Specialization"]


# =========================================================================== #
# Live-Postgres proofs (points 1, 2, 6) — skip cleanly when no DB is reachable.
# The market schema (0007) must be applied: `make migrate-integration`.        #
# =========================================================================== #
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
    """A real connection provider; skips if Postgres / the P6 schema is not reachable."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable at DATABASE_URL — live P6 integration test skipped")
    prov = PostgresConnectionProvider.from_settings()
    try:
        async with prov.session() as session:
            try:
                await session.execute(select(RoleProfile).limit(1))
                await session.execute(select(KbDocument).limit(1))
            except Exception:  # noqa: BLE001 - surface as a skip, not a hard error
                pytest.skip("market schema not applied — run `make migrate-integration`")
        yield prov
    finally:
        await prov.aclose()


async def _seed_taxonomy_occupation(
    provider: PostgresConnectionProvider, *, title: str, source: str, skills: list[str]
) -> None:
    """Seed one shared taxonomy-occupation doc (mirrors the P6-01 seed that always runs).

    Canonicalization (:func:`_resolve_baseline`) matches the occupation taxonomy, so the mine and
    the later read both resolve the target role to this doc's title — the production condition
    (the taxonomy is seeded once, at deploy). Without it, the only curated doc after mining would
    be the role-profile *summary*, and canonicalization would resolve to *its* title instead.
    """
    async with provider.session() as session:
        doc = KbDocument(
            title=title,
            source=source,
            source_type="curated",
            user_id=None,
            content=f"{title} occupation. Typically requires {', '.join(skills)}.",
            meta={"taxonomy_id": "verify:1", "skills": skills, "kind": TAXONOMY_KIND},
        )
        session.add(doc)
        await session.flush()
        await add_kb_chunk(
            session,
            kb_document_id=doc.id,
            chunk_index=0,
            content=f"{title} occupation requires {', '.join(skills)}.",
            embedding=[0.1] * EMBEDDING_DIM,
            meta={},
        )
        await session.commit()


async def _cleanup_role(
    provider: PostgresConnectionProvider, *, canonical: str, taxonomy_source: str
) -> None:
    async with provider.session() as session:
        await session.execute(delete(RoleProfile).where(RoleProfile.canonical_role == canonical))
        await session.execute(delete(JobPosting).where(JobPosting.target_role == canonical))
        await session.execute(
            delete(KbDocument).where(
                KbDocument.user_id.is_(None),
                KbDocument.source.in_([f"role_profile:{canonical}", taxonomy_source]),
            )
        )
        await session.commit()


async def test_live_mining_then_requirements_then_gap(
    provider: PostgresConnectionProvider,
) -> None:
    """Points 1 + 2 (authoritative): a cold role run through the **real** ``mine_role_requirements``
    persists a ``role_profiles`` row; ``GET /api/roles/{role}/requirements`` then returns its
    **frequency-ranked, cited** requirements at 200, and ``GET /api/roles/{role}/gap`` returns a
    sensible matched/gap split — all over the real Postgres, the real service, the real router.

    A taxonomy-occupation doc is seeded first (the production condition — P6-01 seeds the taxonomy
    once at deploy), so canonicalization matches it: the **taxonomy-hit** path (point 1's "fake
    taxonomy hit"), and both the mine and the read resolve the role to the same canonical string.
    Every faked collaborator is a true external edge: the extractor LLM, the Tavily pool, the
    crawl transport, the embedder.
    """
    role = f"Verify Role {uuid.uuid4().hex[:8]}"
    taxonomy_source = f"taxonomy:verify:{role}"
    embedder = _FixedEmbedder()

    await _seed_taxonomy_occupation(
        provider, title=role, source=taxonomy_source, skills=["Python", "SQL"]
    )
    # Guard: on a shared dev DB, only proceed if canonicalization matches our seeded occupation
    # (a pre-existing curated doc outranking it would risk clobbering a real role_profiles row).
    resolved = await resolve_canonical_role(provider, embedder, role)  # type: ignore[arg-type]
    if resolved != role:  # pragma: no cover - defensive on a dirty DB
        await _cleanup_role(provider, canonical=role, taxonomy_source=taxonomy_source)
        pytest.skip(f"canonicalization resolved {role!r} → {resolved!r}; skipping to avoid clobber")

    def crawl_handler_pages() -> httpx.AsyncClient:
        return fake_crawl_client(
            {
                "https://ex.com/job1": "<html><body><p>We need Python and Kubernetes."
                " Email hr@ex.com.</p></body></html>",
                "https://ex.com/job2": "<html><body><p>Requires Python and SQL.</p></body></html>",
            }
        )

    crawl = crawl_handler_pages()
    search = FakeSearchTool(
        [
            {"title": "Job 1", "url": "https://ex.com/job1", "snippet": ""},
            {"title": "Job 2", "url": "https://ex.com/job2", "snippet": ""},
        ]
    )
    # Posting 1 → Python + Kubernetes; posting 2 → Python + SQL. Python is in 2/2 (freq 1.0).
    extractor = _ScriptedExtractor([["Python", "Kubernetes"], ["Python", "SQL"]])

    try:
        mine = await mine_role_requirements(
            role,
            embedder=embedder,  # type: ignore[arg-type]
            db=provider,
            search=search,
            extractor=extractor,
            http_client=crawl,
            robots=_PermissiveRobots(),  # type: ignore[arg-type]
            rate_limiter=_NoWaitLimiter(),  # type: ignore[arg-type]
        )
        await crawl.aclose()

        assert mine["canonical_role"] == role
        assert mine["postings_persisted"] == 2

        # Wire the REAL RolesService over the real provider (fake cache/enqueue, real resolver +
        # real skills-gap over the real DB). Profile store is in-memory (a seeded fixture user).
        profile_store = InMemoryProfileStore()
        user_id = uuid.uuid4().hex
        await profile_store.upsert(user_id, ProfileSchema(skills=["Python"], goals=["Staff"]))

        async def _resolver(role: str) -> str:
            return await resolve_canonical_role(provider, embedder, role)  # type: ignore[arg-type]

        service = RolesService(
            cache=_FakeCache(),
            resolve_canonical=_resolver,
            enqueue_mine=_RecordingEnqueuer(),
            skills_gap=SkillsGapService(profile_store, provider),
            db=provider,
            stale_after_seconds=10_000,
            cache_ttl_seconds=3600,
        )

        app.dependency_overrides[get_roles_service] = lambda: service
        app.dependency_overrides[resolve_optional_user] = lambda: None
        app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service
        app.dependency_overrides[require_auth] = lambda: fake_current_user(
            "s1", role="user", user_id=user_id
        )
        try:
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                req = await c.get(f"/api/roles/{role}/requirements")
                gap = await c.get(f"/api/roles/{role}/gap")
        finally:
            app.dependency_overrides.clear()

        # --- Point 1: cited, frequency-ranked requirements at 200 (not a bare skill list). ---
        assert req.status_code == 200
        rbody = req.json()
        assert rbody["role"] == role
        skills = [r["skill"] for r in rbody["requirements"]]
        assert "Python" in skills
        # Frequency-ranked: Python (in both postings) is the most in-demand, first.
        assert rbody["requirements"][0]["skill"] == "Python"
        assert rbody["requirements"][0]["frequency"] == 1.0
        # Every requirement is cited — evidence carries the backing posting URLs.
        python_req = next(r for r in rbody["requirements"] if r["skill"] == "Python")
        assert python_req["evidence"]  # non-empty citations
        assert rbody["evidence_count"] == 3  # 2 crawled postings + 1 taxonomy baseline

        # --- Point 2: a sensible skills gap (Python matched; the rest are gaps). ---
        assert gap.status_code == 200
        gbody = gap.json()
        assert gbody["status"] == "ok"
        assert "Python" in gbody["matched"]
        gap_skills = [g["skill"] for g in gbody["gap"]]
        assert "Kubernetes" in gap_skills and "SQL" in gap_skills
        assert "Python" not in gap_skills
        # Gap is ordered most-in-demand first (descending frequency).
        freqs = [g["frequency"] for g in gbody["gap"]]
        assert freqs == sorted(freqs, reverse=True)
    finally:
        await _cleanup_role(provider, canonical=role, taxonomy_source=taxonomy_source)


async def test_live_learning_resource_corpus_is_queryable(
    provider: PostgresConnectionProvider,
) -> None:
    """Point 6 (authoritative): a skill-keyed lookup returns a seeded learning resource via the
    **real** JSONB containment query against Postgres — the corpus isn't write-only (§5.7)."""
    skill = f"verifyskill{uuid.uuid4().hex[:8]}"
    source = f"{LEARNING_RESOURCE_KIND}:https://coursera.org/{skill}"

    async with provider.session() as session:
        doc = KbDocument(
            title="A Verify Course",
            source=source,
            source_type="curated",
            user_id=None,
            content=f"A course covering {skill}.",
            meta={
                "kind": LEARNING_RESOURCE_KIND,
                "skill_keys": [skill],  # already lower-cased, as the ingestion pipeline stamps
                "provider": "Coursera",
            },
        )
        session.add(doc)
        await session.flush()
        await add_kb_chunk(
            session,
            kb_document_id=doc.id,
            chunk_index=0,
            content=f"Learn {skill}.",
            embedding=[0.1] * EMBEDDING_DIM,
            meta={"kind": LEARNING_RESOURCE_KIND},
        )
        await session.commit()

    try:
        async with provider.session() as session:
            # Case-insensitive: query with a differently-cased skill than the stored key.
            resources = await list_resources_for_skill(session, skill.upper())
        assert [r.title for r in resources] == ["A Verify Course"]
    finally:
        async with provider.session() as session:
            await session.execute(
                delete(KbDocument).where(KbDocument.user_id.is_(None), KbDocument.source == source)
            )
            await session.commit()
