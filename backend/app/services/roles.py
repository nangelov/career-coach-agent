"""Role-requirements service — cache-first read of the market corpus (P6-07, §5.6 / §5.7 / §8).

The **policy** layer behind the thin ``GET /api/roles/{role}/requirements`` and
``GET /api/roles/{role}/gap`` routes (Router → Service → Repository, §8). It owns the market
surface's read logic so the router stays HTTP-only, and — critically — it guarantees that **no
user-facing turn ever triggers uncached crawling** (§5.6 / §7.5): mining is always enqueued as
a Celery job (:class:`MineRoleEnqueuer`), never awaited on the request path.

``get_requirements`` is **cache-first** (§5.6/§5.7 *"cache hot roles"*):

1. A cheap normalization of the raw path param keys a Redis response cache. A **hit** returns
   the serialized :class:`~app.schemas.roles.RoleRequirementsResponse` verbatim — **no Postgres
   touched at all**, let alone a re-mine (the whole point of caching hot roles).
2. On a **miss**, the role is canonicalized via the shared taxonomy resolver
   (:func:`app.agents.market_agent.resolve_canonical_role` — reused, never reinvented) so the
   lookup and any enqueued mine agree on one ``canonical_role`` string, then the cached
   ``role_profiles`` row is read:

   * **row exists** → build + cache the ranked, cited response (200). If it is older than the
     staleness window, still return it but **enqueue a background refresh** (non-blocking
     "periodic refresh of stale profiles", §5.6).
   * **no row** (never mined) → enqueue a mine job and return its handle (202) for the client to
     poll via the existing ``GET /api/jobs/status/{task_id}`` (P5-06).

``get_gap`` delegates the arithmetic to the P6-05 :class:`~app.services.skills_gap.SkillsGapService`
(reused, not recomputed) after canonicalizing the role, and maps its ``role_profile_missing``
status onto the *same* cold-start behavior (enqueue mine, 202) so a client hitting ``/gap`` cold
still makes forward progress without a second round-trip through ``/requirements``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from app.repositories.market import get_role_profile
from app.schemas.roles import RoleRequirement, RoleRequirementsResponse
from app.services.skills_gap import SessionProvider, SkillsGapService, rank_requirements

if TYPE_CHECKING:
    from app.schemas.skills_gap import SkillsGapResult

__all__ = [
    "CanonicalRoleResolver",
    "MiningAccepted",
    "MineRoleEnqueuer",
    "RequirementsHit",
    "RoleProfileCache",
    "RolesService",
]


class RoleProfileCache(ABC):
    """The Redis-backed serialized-response cache port (interface-before-implementation, §8).

    Keyed on the normalized role; the value is the serialized
    :class:`~app.schemas.roles.RoleRequirementsResponse`. The Redis adapter
    (:class:`~app.repositories.redis.RedisRoleProfileCache`) lives in the repository layer and
    satisfies this port; a unit test injects an in-memory fake — the service never touches a
    driver directly.
    """

    @abstractmethod
    async def get(self, role_key: str) -> str | None:
        """Return the cached serialized response for ``role_key``, or ``None`` on a miss."""

    @abstractmethod
    async def set(self, role_key: str, payload: str, *, ttl_seconds: int) -> None:
        """Cache ``payload`` under ``role_key`` with an expiry of ``ttl_seconds``."""


class CanonicalRoleResolver(Protocol):
    """Normalize a user-stated role to its canonical string (the taxonomy baseline, §5.6).

    Production wraps :func:`app.agents.market_agent.resolve_canonical_role` (taxonomy read over
    the shared pool + embedder); a unit test injects a trivial fake. Injected as a port so the
    service carries no embedder/DB dependency of its own and stays unit-testable.
    """

    async def __call__(self, role: str) -> str: ...


class MineRoleEnqueuer(Protocol):
    """Enqueue a background ``mine_role`` Celery job for ``target_role``; return its task id.

    Production is :func:`app.tasks.market.enqueue_mine_role`; tests inject a fake that records
    the call. Fire-and-forget — the service never awaits the mine's result (§7.5).
    """

    def __call__(self, *, target_role: str) -> str: ...


@dataclass(frozen=True)
class RequirementsHit:
    """``get_requirements`` outcome: the role is mined — serve its ranked profile (→ 200)."""

    response: RoleRequirementsResponse


@dataclass(frozen=True)
class MiningAccepted:
    """``get_requirements`` / ``get_gap`` outcome: role unmined, a mine job was enqueued (202)."""

    task_id: str


class RolesService:
    """Cache-first role-requirements + skills-gap policy (Router → Service → Repository, §8).

    Depends only on ports: a :class:`RoleProfileCache`, a :class:`CanonicalRoleResolver`, a
    :class:`MineRoleEnqueuer`, a :class:`~app.services.skills_gap.SessionProvider` (over which the
    market repository reads ``role_profiles``) and the P6-05
    :class:`~app.services.skills_gap.SkillsGapService`. Built once by the composition root
    (:func:`app.bootstrap.build_roles_service`).
    """

    def __init__(
        self,
        *,
        cache: RoleProfileCache,
        resolve_canonical: CanonicalRoleResolver,
        enqueue_mine: MineRoleEnqueuer,
        skills_gap: SkillsGapService,
        db: SessionProvider,
        stale_after_seconds: int,
        cache_ttl_seconds: int,
    ) -> None:
        self._cache = cache
        self._resolve_canonical = resolve_canonical
        self._enqueue_mine = enqueue_mine
        self._skills_gap = skills_gap
        self._db = db
        self._stale_after_seconds = stale_after_seconds
        self._cache_ttl_seconds = cache_ttl_seconds

    async def get_requirements(self, role: str) -> RequirementsHit | MiningAccepted:
        """Return the role's cached requirement profile, mining in the background if needed.

        Cache-first: a Redis hit short-circuits with zero Postgres access. On a miss the role is
        canonicalized, the ``role_profiles`` row read; an existing row is cached + returned (200,
        with a background refresh enqueued when stale), a missing row enqueues a mine (202).
        """
        cache_key = _cache_key(role)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return RequirementsHit(RoleRequirementsResponse.model_validate_json(cached))

        canonical = await self._resolve_canonical(role)
        async with self._db.session() as session:
            profile = await get_role_profile(session, canonical)

        if profile is None:
            # Never mined → enqueue an async mine job (never a blocking crawl, §7.5) and hand
            # back the poll handle. Not cached: a 202 carries no requirements to serve.
            return MiningAccepted(self._enqueue_mine(target_role=canonical))

        response = RoleRequirementsResponse(
            role=canonical,
            requirements=[
                RoleRequirement(
                    skill=item.skill,
                    frequency=item.frequency,
                    weight=item.weight,
                    evidence=item.evidence,
                )
                for item in rank_requirements(profile.requirements)
            ],
            evidence_count=profile.evidence_count,
            refreshed_at=profile.refreshed_at,
        )
        await self._cache.set(
            cache_key, response.model_dump_json(), ttl_seconds=self._cache_ttl_seconds
        )
        if self._is_stale(profile.refreshed_at):
            # Stale-but-available: still serve it (200), but refresh it off the request path so
            # the *next* caller gets fresher data — the non-blocking periodic refresh (§5.6).
            self._enqueue_mine(target_role=canonical)
        return RequirementsHit(response)

    async def get_gap(self, user_id: str, role: str) -> SkillsGapResult | MiningAccepted:
        """Compute the user's skills gap for ``role``, mining in the background if uncached.

        Canonicalizes the role, then delegates the diff to the P6-05
        :class:`~app.services.skills_gap.SkillsGapService`. A ``role_profile_missing`` status maps
        to the same cold-start behavior as ``get_requirements`` (enqueue mine → 202); ``ok`` and
        ``profile_missing`` are returned as-is for the router to shape (never a 500).
        """
        canonical = await self._resolve_canonical(role)
        result = await self._skills_gap.compute(user_id, canonical)
        if result.status == "role_profile_missing":
            return MiningAccepted(self._enqueue_mine(target_role=canonical))
        return result

    def _is_stale(self, refreshed_at: datetime | None) -> bool:
        """Whether a profile last mined at ``refreshed_at`` is past the staleness window.

        A never-refreshed profile (``None``) is treated as stale so it gets refreshed once.
        """
        if refreshed_at is None:
            return True
        age = (datetime.now(UTC) - refreshed_at).total_seconds()
        return age > self._stale_after_seconds


def _cache_key(role: str) -> str:
    """Cheap, deterministic cache key from the raw path param (whitespace-folded, lower-cased).

    Deliberately **not** the taxonomy canonicalization: the Redis cache must short-circuit
    *before* any DB work (canonicalization itself reads Postgres), which is the whole point of
    caching hot roles (§5.7). Two spellings that canonicalize to the same role simply get two
    cheap cache entries — harmless, and each still resolves to one ``role_profiles`` row on miss.
    """
    return " ".join(role.strip().lower().split())
