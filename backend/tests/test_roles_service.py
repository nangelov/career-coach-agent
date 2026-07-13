"""Unit tests for :class:`~app.services.roles.RolesService` (P6-07, §5.6 / §5.7 / §8).

Drives the service with fakes only (no Postgres/Redis/Celery): an in-memory cache, a spy
canonical resolver, a recording mine-enqueuer, a scripted DB provider yielding a
``role_profiles`` row (or none), and a stub skills-gap. Asserts the cache-first contract — a
second request for the same role is served from Redis with the DB untouched — plus the
cold-start (202) and stale-refresh behaviors.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from app.repositories.models.market import RoleProfile
from app.schemas.roles import RoleRequirementsResponse
from app.schemas.skills_gap import SkillsGapResult
from app.services.roles import MiningAccepted, RequirementsHit, RolesService
from tests.fakes import FakeExecuteResult, FakeSession


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, int]] = []

    async def get(self, role_key: str) -> str | None:
        return self.store.get(role_key)

    async def set(self, role_key: str, payload: str, *, ttl_seconds: int) -> None:
        self.store[role_key] = payload
        self.set_calls.append((role_key, ttl_seconds))


class SpyResolver:
    def __init__(self, canonical: str) -> None:
        self.canonical = canonical
        self.calls = 0

    async def __call__(self, role: str) -> str:
        self.calls += 1
        return self.canonical


class RecordingEnqueuer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *, target_role: str) -> str:
        self.calls.append(target_role)
        return f"task-{len(self.calls)}"


class StubSkillsGap:
    def __init__(self, result: SkillsGapResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def compute(self, user_id: str, role: str) -> SkillsGapResult:
        self.calls.append((user_id, role))
        return self.result


class CountingDB:
    """A DB provider double that counts ``session()`` calls and scripts one role-profile read."""

    def __init__(self, profile: RoleProfile | None) -> None:
        self._profile = profile
        self.sessions = 0

    @asynccontextmanager
    async def session(self) -> Any:
        self.sessions += 1
        rows = [self._profile] if self._profile is not None else []
        yield FakeSession([FakeExecuteResult(rows)])


def _profile(*, refreshed_at: datetime | None, canonical: str = "Data Scientist") -> RoleProfile:
    return RoleProfile(
        canonical_role=canonical,
        requirements={
            "Python": {"frequency": 0.9, "weight": 2.0, "evidence": ["p1"]},
            "SQL": {"frequency": 0.4, "weight": 1.0, "evidence": ["p2"]},
        },
        evidence_count=5,
        refreshed_at=refreshed_at,
    )


def _service(
    *,
    cache: FakeCache,
    resolver: SpyResolver,
    enqueuer: RecordingEnqueuer,
    db: CountingDB,
    skills_gap: StubSkillsGap | None = None,
    stale_after_seconds: int = 10_000,
) -> RolesService:
    gap = skills_gap or StubSkillsGap(SkillsGapResult(role="x", status="ok"))
    return RolesService(
        cache=cache,
        resolve_canonical=resolver,
        enqueue_mine=enqueuer,
        skills_gap=gap,  # type: ignore[arg-type]  # duck-typed stub (SkillsGapService tested in P6-05)
        db=db,  # type: ignore[arg-type]
        stale_after_seconds=stale_after_seconds,
        cache_ttl_seconds=3600,
    )


async def test_cache_miss_hits_db_then_second_request_served_from_redis() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    db = CountingDB(_profile(refreshed_at=datetime.now(UTC)))
    service = _service(cache=cache, resolver=resolver, enqueuer=enqueuer, db=db)

    first = await service.get_requirements("Data Scientist")
    assert isinstance(first, RequirementsHit)
    # Frequency-ranked: Python (0.9) before SQL (0.4); citations preserved.
    assert [r.skill for r in first.response.requirements] == ["Python", "SQL"]
    assert first.response.requirements[0].evidence == ["p1"]
    assert first.response.evidence_count == 5

    second = await service.get_requirements("Data Scientist")
    assert isinstance(second, RequirementsHit)
    # Served from Redis: the DB was hit exactly once and the resolver ran exactly once.
    assert db.sessions == 1
    assert resolver.calls == 1
    assert enqueuer.calls == []


async def test_cache_hit_short_circuits_before_db_and_resolver() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    cached = RoleRequirementsResponse(role="Data Scientist", evidence_count=3)
    cache.store["data scientist"] = cached.model_dump_json()
    db = CountingDB(None)
    service = _service(cache=cache, resolver=resolver, enqueuer=enqueuer, db=db)

    outcome = await service.get_requirements("  Data  Scientist  ")  # normalizes to same key
    assert isinstance(outcome, RequirementsHit)
    assert outcome.response.evidence_count == 3
    assert db.sessions == 0
    assert resolver.calls == 0


async def test_cache_miss_no_profile_enqueues_mine_and_returns_handle() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    db = CountingDB(None)
    service = _service(cache=cache, resolver=resolver, enqueuer=enqueuer, db=db)

    outcome = await service.get_requirements("data scientist")
    assert isinstance(outcome, MiningAccepted)
    assert outcome.task_id == "task-1"
    assert enqueuer.calls == ["Data Scientist"]  # mined under the canonical role
    assert cache.set_calls == []  # a 202 carries no requirements — nothing cached


async def test_stale_profile_served_and_refresh_enqueued() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    old = datetime.now(UTC) - timedelta(seconds=50_000)
    db = CountingDB(_profile(refreshed_at=old))
    service = _service(
        cache=cache, resolver=resolver, enqueuer=enqueuer, db=db, stale_after_seconds=100
    )

    outcome = await service.get_requirements("data scientist")
    assert isinstance(outcome, RequirementsHit)  # stale-but-available still served (200)
    assert enqueuer.calls == ["Data Scientist"]  # background refresh enqueued
    assert cache.set_calls  # the stale response is still cached


async def test_fresh_profile_not_refreshed() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    db = CountingDB(_profile(refreshed_at=datetime.now(UTC)))
    service = _service(
        cache=cache, resolver=resolver, enqueuer=enqueuer, db=db, stale_after_seconds=100
    )

    await service.get_requirements("data scientist")
    assert enqueuer.calls == []


async def test_gap_ok_returned_as_is() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    gap = StubSkillsGap(SkillsGapResult(role="Data Scientist", status="ok", matched=["Python"]))
    service = _service(
        cache=cache, resolver=resolver, enqueuer=enqueuer, db=CountingDB(None), skills_gap=gap
    )

    outcome = await service.get_gap("u1", "data scientist")
    assert isinstance(outcome, SkillsGapResult)
    assert outcome.status == "ok"
    assert gap.calls == [("u1", "Data Scientist")]  # delegated with the canonical role
    assert enqueuer.calls == []


async def test_gap_profile_missing_returned_as_is() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    gap = StubSkillsGap(SkillsGapResult(role="Data Scientist", status="profile_missing"))
    service = _service(
        cache=cache, resolver=resolver, enqueuer=enqueuer, db=CountingDB(None), skills_gap=gap
    )

    outcome = await service.get_gap("u1", "data scientist")
    assert isinstance(outcome, SkillsGapResult)
    assert outcome.status == "profile_missing"
    assert enqueuer.calls == []


async def test_gap_role_profile_missing_enqueues_mine() -> None:
    cache, resolver, enqueuer = FakeCache(), SpyResolver("Data Scientist"), RecordingEnqueuer()
    gap = StubSkillsGap(SkillsGapResult(role="Data Scientist", status="role_profile_missing"))
    service = _service(
        cache=cache, resolver=resolver, enqueuer=enqueuer, db=CountingDB(None), skills_gap=gap
    )

    outcome = await service.get_gap("u1", "data scientist")
    assert isinstance(outcome, MiningAccepted)
    assert outcome.task_id == "task-1"
    assert enqueuer.calls == ["Data Scientist"]
