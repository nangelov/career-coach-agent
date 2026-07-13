"""Skills-gap tests (P6-05, §5.6) — pure diff + thin service wrapper, no DB/network.

Two layers, two test groups:

* :func:`~app.services.skills_gap.compute_skills_gap` — the pure diff: matched/gap partition,
  ordering by frequency then weight, case-insensitive matching, and the empty-profile /
  empty-requirements / malformed-JSONB edges the ``role_profile.requirements`` shape allows.
* :class:`~app.services.skills_gap.SkillsGapService` — the wrapper over an
  :class:`~app.services.profile_store.InMemoryProfileStore` and a scripted
  :class:`~tests.fakes.FakeSession`, covering the happy path plus the two graceful-degradation
  outcomes (no profile, no mined role_profile).
"""

from __future__ import annotations

from app.ingestion.profile import ProfileSchema
from app.repositories.models.market import RoleProfile
from app.services.profile_store import InMemoryProfileStore
from app.services.skills_gap import SkillsGapService, compute_skills_gap
from tests.fakes import FakeDBProvider, FakeExecuteResult, FakeSession

ROLE = "AI Solution Architect"


def _requirements() -> dict[str, dict[str, object]]:
    """A representative role_profile.requirements block (skill → freq/weight/evidence)."""
    return {
        "Python": {"frequency": 0.9, "weight": 3.0, "evidence": ["posting-1", "posting-2"]},
        "RAG": {"frequency": 0.6, "weight": 2.0, "evidence": ["posting-3"]},
        "Kubernetes": {"frequency": 0.4, "weight": 5.0, "evidence": ["posting-4"]},
        "LangGraph": {"frequency": 0.4, "weight": 1.0, "evidence": []},
    }


# --------------------------------------------------------------------------- #
# Pure function                                                               #
# --------------------------------------------------------------------------- #
def test_partitions_matched_and_gap() -> None:
    result = compute_skills_gap(ROLE, ["Python", "RAG"], _requirements())

    assert result.status == "ok"
    assert result.role == ROLE
    assert set(result.matched) == {"Python", "RAG"}
    assert result.gap is not None
    assert {g.skill for g in result.gap} == {"Kubernetes", "LangGraph"}


def test_gap_ordered_by_frequency_then_weight() -> None:
    # Kubernetes and LangGraph both freq 0.4; Kubernetes has the higher weight → first.
    result = compute_skills_gap(ROLE, [], _requirements())

    assert result.gap is not None
    assert [g.skill for g in result.gap] == ["Python", "RAG", "Kubernetes", "LangGraph"]


def test_gap_carries_role_required_payload() -> None:
    result = compute_skills_gap(ROLE, [], {"RAG": _requirements()["RAG"]})

    assert result.gap is not None
    (item,) = result.gap
    assert item.frequency == 0.6
    assert item.weight == 2.0
    assert item.evidence == ["posting-3"]


def test_matching_is_case_insensitive_and_whitespace_tolerant() -> None:
    result = compute_skills_gap(ROLE, ["  pYThOn ", "rag"], _requirements())

    assert set(result.matched) == {"Python", "RAG"}
    # Matched skills speak the role's vocabulary (canonical requirement key), not the CV spelling.
    assert "pYThOn" not in result.matched


def test_empty_profile_makes_every_requirement_a_gap() -> None:
    result = compute_skills_gap(ROLE, [], _requirements())

    assert result.matched == []
    assert result.gap is not None
    assert len(result.gap) == len(_requirements())


def test_empty_requirements_yields_empty_partition() -> None:
    result = compute_skills_gap(ROLE, ["Python"], {})

    assert result.status == "ok"
    assert result.matched == []
    assert result.gap == []


def test_blank_skills_ignored_on_both_sides() -> None:
    result = compute_skills_gap(ROLE, ["", "   "], {"": {"frequency": 1.0}, "  ": {}})

    assert result.matched == []
    assert result.gap == []


def test_malformed_requirement_fields_degrade_gracefully() -> None:
    reqs = {
        "Python": {"frequency": "not-a-number", "weight": None, "evidence": "posting-1"},
        "RAG": "not-a-dict",
    }
    result = compute_skills_gap(ROLE, [], reqs)

    assert result.gap is not None
    by_skill = {g.skill: g for g in result.gap}
    assert by_skill["Python"].frequency == 0.0
    assert by_skill["Python"].weight == 0.0
    # A string evidence value is not treated as a citation list.
    assert by_skill["Python"].evidence == []
    assert by_skill["RAG"].frequency == 0.0
    assert by_skill["RAG"].evidence == []


# --------------------------------------------------------------------------- #
# Service wrapper                                                             #
# --------------------------------------------------------------------------- #
def _role_profile() -> RoleProfile:
    return RoleProfile(canonical_role=ROLE, requirements=_requirements())


def _service(store: InMemoryProfileStore, session: FakeSession) -> SkillsGapService:
    return SkillsGapService(profile_store=store, db=FakeDBProvider(session))


async def test_service_happy_path_resolves_both_inputs() -> None:
    store = InMemoryProfileStore()
    await store.upsert("user-1", ProfileSchema(skills=["Python", "RAG"]))
    session = FakeSession([FakeExecuteResult([_role_profile()])])

    result = await _service(store, session).compute("user-1", ROLE)

    assert result.status == "ok"
    assert set(result.matched) == {"Python", "RAG"}
    assert result.gap is not None
    assert {g.skill for g in result.gap} == {"Kubernetes", "LangGraph"}


async def test_service_no_profile_degrades_without_touching_db() -> None:
    store = InMemoryProfileStore()
    # A session that raises if execute() is called — proves the DB is never hit.
    session = FakeSession([])

    result = await _service(store, session).compute("unknown-user", ROLE)

    assert result.status == "profile_missing"
    assert result.gap is None
    assert session.statements == []


async def test_service_unmined_role_returns_role_profile_missing() -> None:
    store = InMemoryProfileStore()
    await store.upsert("user-1", ProfileSchema(skills=["Python"]))
    session = FakeSession([FakeExecuteResult([])])  # get_role_profile → None

    result = await _service(store, session).compute("user-1", ROLE)

    assert result.status == "role_profile_missing"
    assert result.gap is None
