"""Skills-gap analysis — user profile △ target ``role_profile`` (design §5.6, §5.2 / P7).

The final line of the market pipeline (§5.6: *"skills gap = user profile △ role_profile →
feeds PDP"*). Two layers, so the arithmetic is testable without a DB or network:

* :func:`compute_skills_gap` — the **pure** diff. Given the user's skill names and a role's
  ``requirements`` dict, it partitions required skills into ``matched`` (user already has) and
  ``gap`` (missing, ordered most-in-demand first). No I/O, no stores — fully unit-testable.

* :class:`SkillsGapService` — the **thin wrapper** (Router → Service → Repository, §8): it
  resolves the two inputs (the caller's profile via
  :class:`~app.services.profile_store.ProfileStore`, the target role via
  :func:`app.repositories.market.get_role_profile`) and calls the pure
  function. It never touches the DB driver — the repository helper owns the query and a
  session is handed out by the injected :class:`SessionProvider`. It **degrades gracefully**
  rather than raising: a user with no parsed profile, or a role never mined into
  ``role_profiles``, each returns a clear ``status`` with ``gap=None`` (P6-07 owns the
  "enqueue mining / prompt CV upload" policy — this layer only reads and compares, §5.6).

Matching is a normalized, case-insensitive string compare (``strip().lower()``) — no
embedding/fuzzy matcher (a documented simplification for this task; a smarter matcher can
replace :func:`_normalize`/the membership test behind the same contract later).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Protocol

from app.repositories.market import get_role_profile
from app.schemas.skills_gap import SkillGap, SkillsGapResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.profile_store import ProfileStore

__all__ = [
    "SessionProvider",
    "SkillsGapService",
    "compute_skills_gap",
    "rank_requirements",
]


class SessionProvider(Protocol):
    """The DB capability the wrapper needs: hand out a pooled ``AsyncSession``.

    A structural :class:`~typing.Protocol` (not a hard import of
    :class:`~app.repositories.postgres.PostgresConnectionProvider`) so the service depends on a
    *capability*, not a concrete class — the shared-pool provider satisfies it in production and
    a unit test injects a scripted fake. Mirrors the worker-side seam of the same name; its
    :meth:`session` context manager works outside a FastAPI request, which a service call needs.
    """

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


def _normalize(skill: str) -> str:
    """Fold a skill name to its comparison key: trimmed and lower-cased (case-insensitive match)."""
    return skill.strip().lower()


def _coerce_float(value: Any) -> float:
    """Best-effort float from a JSONB requirement field (defensive: bad/absent → ``0.0``)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_evidence(value: Any) -> list[Any]:
    """Best-effort citation list from a JSONB ``evidence`` field (a str/absent value → ``[]``)."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _to_skill_gap(skill: str, spec: Any) -> SkillGap:
    """Build one :class:`SkillGap` from a role's ``requirements[skill]`` entry (defensive JSONB).

    The single place the ``{frequency, weight, evidence}`` shape is coerced (§5.1 graceful
    degradation): a malformed/absent ``frequency``/``weight`` → ``0.0`` and a non-list
    ``evidence`` → ``[]``. Reused by :func:`rank_requirements` and :func:`compute_skills_gap`.
    """
    detail = spec if isinstance(spec, Mapping) else {}
    return SkillGap(
        skill=skill,
        frequency=_coerce_float(detail.get("frequency")),
        weight=_coerce_float(detail.get("weight")),
        evidence=_coerce_evidence(detail.get("evidence")),
    )


def rank_requirements(role_requirements: Mapping[str, Any]) -> list[SkillGap]:
    """Rank **all** of a role's requirements most-in-demand first (pure — no diff, no I/O).

    The frequency-ranked view of a ``role_profile.requirements`` dict (§5.6): every named
    requirement becomes a :class:`SkillGap` carrying its ``frequency``/``weight``/``evidence``,
    ordered by descending ``frequency`` then ``weight`` with the skill name as a stable
    tie-break. Powers ``GET /api/roles/{role}/requirements`` (P6-07) so the ranking + defensive
    coercion live in one place, shared with :func:`compute_skills_gap`.
    """
    ranked = [
        _to_skill_gap(skill, spec)
        for skill, spec in role_requirements.items()
        if skill and skill.strip()
    ]
    ranked.sort(key=lambda g: (-g.frequency, -g.weight, g.skill.lower()))
    return ranked


def compute_skills_gap(
    role: str,
    profile_skills: Iterable[str],
    role_requirements: Mapping[str, Any],
) -> SkillsGapResult:
    """Diff a user's skills against a role's ``requirements`` (pure — the unit-testable heart).

    ``role_requirements`` is the ``role_profile.requirements`` shape
    ``{skill: {frequency, weight, evidence}}`` (§5.6). Each required skill lands in either:

    * ``matched`` — the user has it (normalized case-insensitive compare), keyed by the role's
      requirement name (so the contract speaks the role's vocabulary, not the CV's spelling);
    * ``gap`` — the user lacks it, carrying the role-required ``frequency``/``weight``/``evidence``
      verbatim, **ordered most-in-demand first** (descending ``frequency``, then ``weight``,
      with the skill name as a stable tie-break so the order is deterministic).

    Robust to the edges the schema allows: an empty profile makes every requirement a gap; empty
    requirements yield empty ``matched``/``gap``; a malformed/absent ``frequency``/``weight``
    coerces to ``0.0`` and a non-list ``evidence`` to ``[]`` (graceful degradation, §5.1). Always
    returns ``status="ok"`` — availability of the inputs is the wrapper's concern.
    """
    have = {_normalize(s) for s in profile_skills if s and s.strip()}

    matched: list[str] = []
    gap: list[SkillGap] = []
    for skill, spec in role_requirements.items():
        if not skill or not skill.strip():
            continue
        if _normalize(skill) in have:
            matched.append(skill)
            continue
        gap.append(_to_skill_gap(skill, spec))

    gap.sort(key=lambda g: (-g.frequency, -g.weight, g.skill.lower()))
    return SkillsGapResult(role=role, status="ok", matched=matched, gap=gap)


class SkillsGapService:
    """Resolve profile + role inputs and compute the gap (Router → Service → Repository, §8).

    Depends only on ports: the :class:`~app.services.profile_store.ProfileStore` for the caller's
    structured profile and a :class:`SessionProvider` over which the market repository reads the
    cached role profile — no SQLAlchemy in the service body. Built once by the composition root;
    P6-07 wires it into ``GET /api/roles/{role}/gap``.
    """

    def __init__(self, profile_store: ProfileStore, db: SessionProvider) -> None:
        self._profile_store = profile_store
        self._db = db

    async def compute(self, user_id: str, role: str) -> SkillsGapResult:
        """Compute the skills gap for ``user_id`` against ``role``, degrading gracefully.

        Order of resolution mirrors the precondition chain: a gap needs a profile *and* a mined
        role, so a missing profile short-circuits to ``profile_missing`` before the DB is touched,
        and an unmined role returns ``role_profile_missing`` (``gap=None`` in both — P6-07 decides
        whether to prompt a CV upload or enqueue mining). Neither raises; neither triggers a crawl.
        """
        profile = await self._profile_store.get(user_id)
        if profile is None:
            return SkillsGapResult(role=role, status="profile_missing")

        async with self._db.session() as session:
            role_profile = await get_role_profile(session, role)
        if role_profile is None:
            return SkillsGapResult(role=role, status="role_profile_missing")

        return compute_skills_gap(role, profile.skills, role_profile.requirements)
