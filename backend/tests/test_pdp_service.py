"""Unit tests for the PDP service (P7-03, §5.2) — the generate → validate → persist flow.

Driven with fakes only (no real HF / Postgres): the real
:func:`~app.agents.pdp_agent.generate_pdp` runs over a scripted ``LLMCompleter`` (whose forced
``record_pdp`` tool call decides the plan's substance), the reused
:class:`~app.services.skills_gap.SkillsGapService` runs over an in-memory profile store + a
scripted session (role-profile hit/miss), and an :class:`~app.services.pdp_store.InMemoryPdpStore`
records the persisted row. Asserts the design-critical policy: a missing profile short-circuits, an
unmined role degrades to a best-effort plan, every returned PDF is validation-gated with one
bounded retry, and a row is persisted per successful generation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from app.agents.pdp_agent import PDP_TOOL_NAME
from app.ingestion.profile import ProfileSchema
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import CompletionResult, FunctionCall, ToolCall
from app.schemas.pdp import SECTION_HEADINGS
from app.services.pdp import (
    PdpGenerated,
    PdpGenerationFailed,
    PdpProfileMissing,
    PdpService,
)
from app.services.pdp_store import InMemoryPdpStore
from app.services.profile_store import InMemoryProfileStore
from app.services.skills_gap import SkillsGapService
from tests.fakes import FakeDBProvider, FakeExecuteResult, FakeSession

_USER = "11111111-1111-1111-1111-111111111111"
_ROLE = "Data Scientist"

#: A full six-section plan (well over the 500-char / 4-section validation floor).
_FULL_SECTIONS = {field: f"{heading} body. " * 20 for field, heading in SECTION_HEADINGS}
#: A too-thin plan (only two non-empty sections) — fails ``validate_pdp_content``.
_THIN_SECTIONS = {"current_skills_assessment": "x", "recommended_training": "y"}


class SeqCompleter:
    """A scripted ``LLMCompleter`` returning a queued ``record_pdp`` call per invocation."""

    def __init__(self, section_dicts: Sequence[dict[str, str]]) -> None:
        self._queue = list(section_dicts)
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Any],
        *,
        tools: Sequence[Any] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        sections = self._queue.pop(0)
        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    function=FunctionCall(name=PDP_TOOL_NAME, arguments=json.dumps(sections)),
                )
            ],
            model="fake",
        )


class RaisingCompleter:
    """A scripted ``LLMCompleter`` whose every ``complete`` call raises an ``LLMError``.

    Drives the LLM-outage path: the agent catches the error, reports ``generation_failed``, and
    the service must map that to :class:`PdpGenerationFailed` (never a persisted placeholder plan).
    """

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Any],
        *,
        tools: Sequence[Any] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        raise LLMAllModelsFailedError("all models down")


def _profile() -> ProfileSchema:
    return ProfileSchema(skills=["Python"], goals=["Grow into a data role"])


def _role_profile_session(requirements: dict[str, Any]) -> FakeSession:
    """A session whose single read returns a mined role profile with ``requirements``."""
    return FakeSession(
        [FakeExecuteResult([SimpleNamespace(canonical_role=_ROLE, requirements=requirements)])]
    )


def _no_role_session() -> FakeSession:
    """A session whose single read returns no role profile (the role was never mined)."""
    return FakeSession([FakeExecuteResult([])])


def _service(
    *,
    profile: ProfileSchema | None,
    role_session: FakeSession,
    completer: SeqCompleter | RaisingCompleter,
    pdp_store: InMemoryPdpStore,
) -> PdpService:
    profile_store = InMemoryProfileStore()
    if profile is not None:
        # Seed the stored profile (mirrors a prior CV parse) via the port's upsert.
        profile_store._by_user[_USER] = profile  # noqa: SLF001 - test seeding of the double
    skills_gap = SkillsGapService(profile_store, FakeDBProvider(role_session))
    return PdpService(
        profile_store=profile_store,
        skills_gap=skills_gap,
        pdp_store=pdp_store,
        router=completer,  # type: ignore[arg-type] - structural LLMCompleter double
        db=FakeDBProvider(FakeSession([])),  # gap is empty in these tests → no resource lookup
    )


# --------------------------------------------------------------------------- #
# Happy path — profile + mined role → validated PDF + persisted row
# --------------------------------------------------------------------------- #
async def test_happy_path_returns_pdf_and_persists_one_row() -> None:
    completer = SeqCompleter([_FULL_SECTIONS])
    store = InMemoryPdpStore()
    service = _service(
        profile=_profile(),
        role_session=_role_profile_session({"Python": {"frequency": 0.9, "weight": 1.0}}),
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal=_ROLE, target_date=None)

    assert isinstance(outcome, PdpGenerated)
    assert outcome.status == "ok"
    assert outcome.pdf.startswith(b"%PDF")  # a real rendered PDF, not a stub
    assert completer.calls == 1  # passed validation first try, no retry
    assert len(store.saved) == 1
    saved = store.saved[0]
    assert saved.user_id == _USER
    assert saved.career_goal == _ROLE
    assert saved.content.status == "ok"
    assert outcome.pdp_id == saved.id


# --------------------------------------------------------------------------- #
# Missing profile — short-circuit, no LLM call, no persisted row
# --------------------------------------------------------------------------- #
async def test_missing_profile_short_circuits_before_llm() -> None:
    completer = SeqCompleter([_FULL_SECTIONS])
    store = InMemoryPdpStore()
    service = _service(
        profile=None,
        role_session=_no_role_session(),
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal=_ROLE, target_date=None)

    assert isinstance(outcome, PdpProfileMissing)
    assert completer.calls == 0  # no LLM call made
    assert store.saved == []  # nothing persisted


# --------------------------------------------------------------------------- #
# Unmined role — best-effort plan (role_profile_missing), still a PDF + row
# --------------------------------------------------------------------------- #
async def test_unmined_role_degrades_to_best_effort_plan() -> None:
    completer = SeqCompleter([_FULL_SECTIONS])
    store = InMemoryPdpStore()
    service = _service(
        profile=_profile(),
        role_session=_no_role_session(),  # role never mined
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal="Rare Role", target_date=None)

    assert isinstance(outcome, PdpGenerated)
    assert outcome.status == "role_profile_missing"
    assert completer.calls == 1  # best-effort plan is still generated
    assert len(store.saved) == 1


# --------------------------------------------------------------------------- #
# Validation retry — a thin first plan is retried once, then succeeds
# --------------------------------------------------------------------------- #
async def test_thin_plan_is_retried_once_then_succeeds() -> None:
    completer = SeqCompleter([_THIN_SECTIONS, _FULL_SECTIONS])
    store = InMemoryPdpStore()
    service = _service(
        profile=_profile(),
        role_session=_role_profile_session({"Python": {"frequency": 0.9, "weight": 1.0}}),
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal=_ROLE, target_date=None)

    assert isinstance(outcome, PdpGenerated)
    assert completer.calls == 2  # first plan failed validation, retried once
    assert len(store.saved) == 1  # only the passing plan is persisted


# --------------------------------------------------------------------------- #
# Validation retry exhausted — a persistently thin plan is a clear error, no row
# --------------------------------------------------------------------------- #
async def test_persistently_thin_plan_fails_without_persisting() -> None:
    completer = SeqCompleter([_THIN_SECTIONS, _THIN_SECTIONS])
    store = InMemoryPdpStore()
    service = _service(
        profile=_profile(),
        role_session=_role_profile_session({"Python": {"frequency": 0.9, "weight": 1.0}}),
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal=_ROLE, target_date=None)

    assert isinstance(outcome, PdpGenerationFailed)
    assert completer.calls == 2  # one initial try + one bounded retry
    assert store.saved == []  # never persist a broken plan


# --------------------------------------------------------------------------- #
# LLM outage — synthesis failure surfaces as a clear error, never a placeholder plan
# --------------------------------------------------------------------------- #
async def test_llm_outage_fails_without_persisting_placeholder_plan() -> None:
    completer = RaisingCompleter()
    store = InMemoryPdpStore()
    service = _service(
        profile=_profile(),
        role_session=_role_profile_session({"Python": {"frequency": 0.9, "weight": 1.0}}),
        completer=completer,
        pdp_store=store,
    )

    outcome = await service.generate(user_id=_USER, career_goal=_ROLE, target_date=None)

    # The agent's honest placeholder text passes the length gate, so without the explicit
    # generation_failed signal this would have been persisted/returned as a 200 PDF (the C1 bug).
    assert isinstance(outcome, PdpGenerationFailed)
    assert completer.calls == 2  # one initial try + one bounded retry, both raised
    assert store.saved == []  # never persist a placeholder plan
