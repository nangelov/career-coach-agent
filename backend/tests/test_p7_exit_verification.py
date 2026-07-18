"""P7 phase-exit verification (P7-05) — the PDP chain, end to end.

A **verification-only** module (no product code changed): it ties the P7 building blocks
together and drives them as a single story, proving the plan.md P7 exit criterion:

    "PDP PDF matches/exceeds v1 quality, grounded in the user's stored profile."

The prior per-task suites prove each piece in isolation (``test_pdp_agent`` — the agent;
``test_pdf_builder`` — the renderer/gate; ``test_pdp_service`` — the policy loop;
``test_pdp_api`` — the router over a *fake* service). **This** module proves they *compose*:
a fixture profile + a mined role's skills gap + a corpus resource-lookup run through the
**real** :func:`~app.agents.pdp_agent.generate_pdp` → **real**
:func:`~app.pdf.validate_pdp_content` → **real** :func:`~app.pdf.build_pdp_pdf` → the **real**
:class:`~app.services.pdp.PdpService` → the **real** ``POST /api/pdp`` router, faking only the
true external edges (the LLM completions and the DB sessions), mirroring the P4-10 / P5-08 /
P6-09 posture ("real stack, in-memory/fake ports, no live HF / live Postgres").

Coverage of the P7-05 task's five points:

1. **Section-header contract stays in one place** — ``test_section_headings_single_source_*``
   (source scan: only :mod:`app.schemas.pdp` carries the six-heading list; the agent and the
   PDF builder reference ``SECTION_HEADINGS``, never a second hardcoded copy).
2. **End-to-end generation → valid, styled, grounded PDF** —
   ``test_end_to_end_generation_produces_grounded_styled_pdf`` (real generate → validate →
   render; the PDF starts with ``%PDF``, is non-trivial, and the gap skills + cited resources
   that went in are traceable in the ``PdpContent`` that came out — deduped, not hallucinated).
3. **Quality vs v1** — ``test_rendered_plan_meets_v1_contract`` (the v2 rendered markdown passes
   the *v1* ``validate_pdp_response`` gate — same six sections, ≥500 chars, no ReAct scaffolding)
   + ``test_pdf_carries_v1_styling_tiers_and_v2_additions`` (same title/heading/subheading/body
   styling tiers **plus** the cited-resource list v1 lacked).
4. **Degraded paths don't silently regress** — ``test_missing_profile_is_422_no_pdf_no_row``,
   ``test_unmined_role_best_effort_pdf_with_status_header``, and
   ``test_llm_outage_is_502_no_row_no_placeholder_pdf`` (the P7-03 rev-2 fix: an LLM outage's
   honest placeholder must never slip past the gate as a 200 PDF) — all over the **real**
   service chain through the endpoint.
5. **``POST /api/pdp`` download round trip** — ``test_download_round_trip_bytes_uncorrupted``
   (the response body is *exactly* the bytes the real builder produced, with an
   ``application/pdf`` type and a sane ``PDP_<goal>.pdf`` filename).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from httpx import ASGITransport

from app.agents.pdp_agent import PDP_TOOL_NAME, PDP_TOOL_SCHEMA, generate_pdp
from app.api.pdp import get_pdp_service
from app.ingestion.profile import EducationItem, ExperienceItem, ProfileSchema
from app.llm.errors import LLMAllModelsFailedError
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall
from app.main import app
from app.pdf import build_pdp_pdf, validate_pdp_content
from app.repositories.learning_resources import LEARNING_RESOURCE_KIND
from app.repositories.models.knowledge import KbDocument
from app.schemas.pdp import SECTION_HEADINGS, PdpContent
from app.schemas.skills_gap import SkillsGapResult
from app.security.dependencies import get_rate_limit_service, require_auth
from app.services.pdp import PdpGenerated, PdpResult, PdpService
from app.services.pdp_store import InMemoryPdpStore
from app.services.profile_store import InMemoryProfileStore
from app.services.skills_gap import SkillsGapService
from tests.fakes import (
    FakeDBProvider,
    FakeExecuteResult,
    FakeSession,
    fake_current_user,
    unlimited_rate_limit_service,
)

_USER = "22222222-2222-2222-2222-222222222222"
_ROLE = "Data Scientist"

#: A substantial six-section plan (well over the 500-char / 4-section validation floor). The
#: bodies echo their heading so the rendered plan is realistic; grounding is proven separately
#: (the resources are deterministically injected by the agent, not written by this script).
_FULL_SECTIONS = {field: f"{heading} body. " * 20 for field, heading in SECTION_HEADINGS}


# =========================================================================== #
# Shared test doubles (edges only — the PDP pipeline in between is real).      #
# =========================================================================== #
class _RecordingSeqCompleter:
    """A scripted ``LLMCompleter`` forcing ``record_pdp``; records the messages it was handed.

    Returns the next queued section dict as a native ``record_pdp`` tool call (no free-text
    parsing) so the **real** agent fence + forced-tool-choice + parse path runs over it — the
    only faked edge is the model. :attr:`calls_messages` lets a test assert the fenced grounding
    (profile / gap / resources) actually reached the model.
    """

    def __init__(self, section_dicts: Sequence[dict[str, str]]) -> None:
        self._queue = [dict(s) for s in section_dicts]
        self.calls_messages: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[Any] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls_messages.append(list(messages))
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


class _RaisingCompleter:
    """A scripted ``LLMCompleter`` whose every ``complete`` raises — models a total LLM outage."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[Any] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        raise LLMAllModelsFailedError("all models down")


def _fixture_profile() -> ProfileSchema:
    """A realistic stored profile (the P5 output the PDP is grounded in — §5.2)."""
    return ProfileSchema(
        skills=["Python", "Pandas"],
        goals=["Grow into a senior data role"],
        experience=[
            ExperienceItem(
                title="Data Analyst",
                company="Acme",
                start_date="2021",
                end_date="2024",
                description="Built reporting pipelines.",
            )
        ],
        education=[EducationItem(institution="State Uni", degree="BSc", field="Statistics")],
    )


def _role_profile_row(requirements: dict[str, Any]) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(canonical_role=_ROLE, requirements=requirements)


def _resource_doc(*, title: str, url: str, provider: str, skill: str) -> KbDocument:
    """One curated learning-resource ``KbDocument`` as the corpus lookup returns it (§5.7)."""
    return KbDocument(
        title=title,
        source=f"{LEARNING_RESOURCE_KIND}:{url}",
        source_type="curated",
        user_id=None,
        content=f"A course covering {skill}.",
        meta={"kind": LEARNING_RESOURCE_KIND, "provider": provider, "url": url},
    )


def _real_service(
    *,
    profile: ProfileSchema | None,
    role_session: FakeSession,
    resource_session: FakeSession,
    completer: _RecordingSeqCompleter | _RaisingCompleter,
    store: InMemoryPdpStore,
) -> PdpService:
    """Assemble the **real** :class:`PdpService` with fakes only at the LLM + DB edges."""
    profile_store = InMemoryProfileStore()
    if profile is not None:
        profile_store._by_user[_USER] = profile  # noqa: SLF001 - seed the double
    skills_gap = SkillsGapService(profile_store, FakeDBProvider(role_session))
    return PdpService(
        profile_store=profile_store,
        skills_gap=skills_gap,
        pdp_store=store,
        router=completer,
        db=FakeDBProvider(resource_session),
    )


class _CapturingPdpService:
    """Wraps the real service, recording the :class:`PdpResult` it returned (round-trip proof)."""

    def __init__(self, inner: PdpService) -> None:
        self._inner = inner
        self.last: PdpResult | None = None

    async def generate(self, **kwargs: Any) -> PdpResult:
        self.last = await self._inner.generate(**kwargs)
        return self.last


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _override_authed_user() -> None:
    app.dependency_overrides[require_auth] = lambda: fake_current_user(
        "s1", role="user", user_id=_USER
    )
    app.dependency_overrides[get_rate_limit_service] = unlimited_rate_limit_service


# =========================================================================== #
# 1. Section-header contract stays in exactly one place.                       #
# =========================================================================== #
_SRC_ROOT = Path(__file__).resolve().parents[1] / "app"
_HEADINGS = [heading for _field, heading in SECTION_HEADINGS]


def test_section_headings_single_source_in_schema() -> None:
    """:mod:`app.schemas.pdp` is the one home of the six v1 headings — all six live there."""
    schema_src = (_SRC_ROOT / "schemas" / "pdp.py").read_text(encoding="utf-8")
    assert all(heading in schema_src for heading in _HEADINGS)
    # And they are exactly the v1 six, in v1 order (the contract legacy `validate_pdp_response`
    # gated on — legacy-code/output_parser.py:368).
    assert _HEADINGS == [
        "Current Skills Assessment",
        "Skills Gap Analysis",
        "Learning Objectives and Milestones",
        "Recommended Training and Development",
        "Timeline and Action Steps",
        "Progress Tracking and KPIs",
    ]


def test_section_headings_not_re_hardcoded_in_agent_or_builder() -> None:
    """Neither the agent nor the PDF builder hardcodes a *second* copy of the six-heading list.

    Both must derive the section set from ``SECTION_HEADINGS`` (they import + iterate it), so a
    stray full duplicate would let the contract drift. A heading may appear once in prose/docs
    (e.g. "under *Recommended Training and Development*"); a genuine second copy would surface
    all six. We assert both: the symbol is referenced, and fewer than six literal headings occur.
    """
    for rel in ("agents/pdp_agent.py", "pdf/builder.py"):
        src = (_SRC_ROOT / rel).read_text(encoding="utf-8")
        assert "SECTION_HEADINGS" in src, f"{rel} should derive sections from SECTION_HEADINGS"
        present = sum(1 for heading in _HEADINGS if heading in src)
        assert present < 6, f"{rel} appears to hardcode a second full copy of the section list"


# =========================================================================== #
# 2. End-to-end generation → valid, styled, grounded PDF.                      #
# =========================================================================== #
async def test_end_to_end_generation_produces_grounded_styled_pdf() -> None:
    """The whole chain over the real agent+builder: a profile + mined gap + corpus resources →
    a valid ``PdpContent`` → a validated, styled PDF; the inputs are traceable in the output.

    Grounding proof (§5.6 / §5.7): the two ranked gap skills reach the model's fenced prompt,
    and the cited resources on the returned ``PdpContent`` are *exactly* the corpus docs the
    lookup returned (deduped by URL — a course surfaced by two skills is cited once, carrying
    both), never invented by the model.
    """
    requirements = {
        "Python": {"frequency": 1.0, "weight": 2.0, "evidence": ["https://ex.com/p1"]},
        "Kubernetes": {"frequency": 0.8, "weight": 1.5, "evidence": ["https://ex.com/p2"]},
        "SQL": {"frequency": 0.4, "weight": 1.0, "evidence": ["https://ex.com/p3"]},
    }
    skills_gap = _skills_gap_from(requirements, profile_skills=["Python", "Pandas"])
    # gap is [Kubernetes(0.8), SQL(0.4)] — one lookup per skill, in that order.
    shared = _resource_doc(
        title="Cloud Native Fundamentals", url="https://ex.com/c", provider="edX", skill="shared"
    )
    resource_session = FakeSession(
        [
            FakeExecuteResult(
                [
                    _resource_doc(
                        title="Kubernetes Deep Dive",
                        url="https://ex.com/k",
                        provider="Coursera",
                        skill="Kubernetes",
                    ),
                    shared,
                ]
            ),
            FakeExecuteResult(
                [
                    shared,
                    _resource_doc(
                        title="SQL for Analysts",
                        url="https://ex.com/s",
                        provider="Udemy",
                        skill="SQL",
                    ),
                ]
            ),
        ]
    )
    completer = _RecordingSeqCompleter([_FULL_SECTIONS])

    content = await generate_pdp(
        profile=_fixture_profile(),
        skills_gap=skills_gap,
        career_goal=_ROLE,
        target_date="2027-01-01",
        router=completer,
        db=FakeDBProvider(resource_session),
    )

    # --- Grounded: the ranked gap reached the model's fenced prompt (most-in-demand first). ---
    prompt = "\n".join(m.content or "" for m in completer.calls_messages[0] if m.role == "system")
    assert "Kubernetes" in prompt and "SQL" in prompt
    assert prompt.index("Kubernetes") < prompt.index("SQL")  # descending-frequency order

    # --- Grounded: cited resources are the corpus docs (deduped by URL), not hallucinated. ---
    assert content.status == "ok"
    by_url = {r.url: r for r in content.resources}
    assert set(by_url) == {"https://ex.com/k", "https://ex.com/c", "https://ex.com/s"}
    assert sorted(by_url["https://ex.com/c"].skills) == ["Kubernetes", "SQL"]  # deduped, both

    # --- Valid + styled: the plan passes the render gate and produces a real PDF. ---
    assert validate_pdp_content(content) is True
    pdf = build_pdp_pdf(content, _ROLE, "2027-01-01")
    assert pdf.startswith(b"%PDF")  # PDF magic
    assert len(pdf) > 1500  # non-trivial, not an empty stub


def _skills_gap_from(requirements: dict[str, Any], *, profile_skills: list[str]) -> SkillsGapResult:
    """Compute a real :class:`SkillsGapResult` (the P6-05 arithmetic) for the fixture inputs."""
    from app.services.skills_gap import compute_skills_gap

    return compute_skills_gap(_ROLE, profile_skills, requirements)


# =========================================================================== #
# 3. Quality vs v1 — meets the v1 contract, plus v2 additions.                 #
# =========================================================================== #
#: The v1 PDP acceptance contract, transcribed from legacy-code/output_parser.py
#: ``validate_pdp_response`` (its imports pull LangChain, absent in v2, so it is not imported).
_V1_MIN_CHARS = 500
_V1_REQUIRED_SECTIONS = (
    "Current Skills Assessment",
    "Skills Gap Analysis",
    "Learning Objectives",
    "Recommended Training",
    "Timeline",
    "Progress Tracking",
)
_V1_PROBLEMATIC = ("```python", "SyntaxError", "Action:", "Action Input:", "Observation:")


def _passes_v1_pdp_gate(text: str) -> bool:
    """Replicate v1's ``validate_pdp_response`` exactly (the baseline v2 must meet)."""
    if len(text.strip()) < _V1_MIN_CHARS:
        return False
    found = sum(1 for s in _V1_REQUIRED_SECTIONS if s.lower() in text.lower())
    if found < 4:
        return False
    return not any(p in text for p in _V1_PROBLEMATIC)


def test_rendered_plan_meets_v1_contract() -> None:
    """A v2 plan's rendered markdown passes the **v1** gate: same six sections, ≥500 chars, and —
    by the forced-tool-call design (P7-01) — never any ReAct scaffolding (``Action:`` etc.).

    ``to_markdown`` supplies the headings deterministically, so the v1 "≥4 of 6 headings present"
    and "no scaffolding" checks both hold structurally, not by luck of the model's phrasing.
    """
    content = PdpContent(status="ok", **_FULL_SECTIONS)
    markdown = content.to_markdown()

    assert _passes_v1_pdp_gate(markdown)
    # All six v1 sections are present (v2 meets, not just 4/6).
    assert all(s.lower() in markdown.lower() for s in _V1_REQUIRED_SECTIONS)
    # The v2 gate agrees with the v1 gate on this plan.
    assert validate_pdp_content(content) is True


def test_pdf_carries_v1_styling_tiers_and_v2_additions() -> None:
    """v2 keeps v1's four styling tiers (title/heading/subheading/body) **and** adds the cited
    learning-resource list v1 never had (§5.7) — meeting *and* exceeding v1.

    The four style tiers are the same reportlab styles v1 defined
    (legacy-code/helpers/helper.py — CustomTitle/CustomHeading/CustomSubHeading/CustomBody); the
    resource citation is a v2 addition (v1 rendered a flat markdown blob with no structured
    citations). We prove the addition renders a larger document than the same plan without it.
    """
    from app.pdf.builder import _build_styles

    styles = _build_styles()
    assert set(styles) == {"title", "heading", "subheading", "body"}  # same four v1 tiers

    with_resources = PdpContent(
        status="ok",
        resources=[
            _cited("Kubernetes Deep Dive", "Coursera", "https://ex.com/k", ["Kubernetes"]),
            _cited("SQL for Analysts", "Udemy", "https://ex.com/s", ["SQL"]),
        ],
        **_FULL_SECTIONS,
    )
    without_resources = PdpContent(status="ok", **_FULL_SECTIONS)

    pdf_with = build_pdp_pdf(with_resources, _ROLE, None)
    pdf_without = build_pdp_pdf(without_resources, _ROLE, None)
    assert pdf_with.startswith(b"%PDF") and pdf_without.startswith(b"%PDF")
    # The cited-resource block (a v2 addition) renders extra content → a larger document.
    assert len(pdf_with) > len(pdf_without)


def _cited(title: str, provider: str, url: str, skills: list[str]) -> Any:
    from app.schemas.pdp import LearningResourceRef

    return LearningResourceRef(title=title, provider=provider, url=url, skills=skills)


def test_pdp_tool_schema_is_the_forced_six_section_contract() -> None:
    """The agent forces a native ``record_pdp`` tool call whose properties mirror the six
    sections — so the plan is structured output, never a ReAct text blob a parser must clean
    (locked decision §6: no ReAct parser). This is why scaffolding is *structurally* impossible.
    """
    fn = PDP_TOOL_SCHEMA["function"]
    assert fn["name"] == PDP_TOOL_NAME
    props = fn["parameters"]["properties"]
    assert set(props) == {field for field, _heading in SECTION_HEADINGS}
    assert set(fn["parameters"]["required"]) == {field for field, _heading in SECTION_HEADINGS}


# =========================================================================== #
# 4 + 5. Degraded paths + download round trip through the REAL service chain.  #
# =========================================================================== #
async def test_download_round_trip_bytes_uncorrupted(client: httpx.AsyncClient) -> None:
    """Point 5: ``POST /api/pdp`` returns *exactly* the bytes the real builder produced.

    The real :class:`PdpService` runs the whole chain (real gap → real generate → real validate →
    real render → in-memory persist); a capturing wrapper records the :class:`PdpGenerated` it
    returned, and we assert the HTTP body is byte-identical (no corruption through the response
    path), ``application/pdf``, and carries a sane ``PDP_<goal>.pdf`` filename + ``X-PDP-Status``.
    """
    requirements = {"Python": {"frequency": 0.9, "weight": 1.0, "evidence": ["u1"]}}
    store = InMemoryPdpStore()
    inner = _real_service(
        profile=_fixture_profile(),
        role_session=FakeSession([FakeExecuteResult([_role_profile_row(requirements)])]),
        resource_session=FakeSession([]),  # Python is matched → no gap → no resource lookup
        completer=_RecordingSeqCompleter([_FULL_SECTIONS]),
        store=store,
    )
    capturing = _CapturingPdpService(inner)

    app.dependency_overrides[get_pdp_service] = lambda: capturing
    _override_authed_user()
    try:
        response = await client.post(
            "/api/pdp", json={"career_goal": _ROLE, "target_date": "2027-01-01"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "PDP_Data-Scientist.pdf" in response.headers["content-disposition"]
    assert response.headers["x-pdp-status"] == "ok"
    assert isinstance(capturing.last, PdpGenerated)
    assert response.content == capturing.last.pdf  # byte-identical, uncorrupted
    assert response.content.startswith(b"%PDF")
    assert len(store.saved) == 1  # exactly one persisted row per generation


async def test_missing_profile_is_422_no_pdf_no_row(client: httpx.AsyncClient) -> None:
    """Point 4: no stored profile → 422 (upload a CV), no LLM call, no PDF, no persisted row —
    over the real service chain (not a fake outcome)."""
    completer = _RecordingSeqCompleter([_FULL_SECTIONS])
    store = InMemoryPdpStore()
    inner = _real_service(
        profile=None,
        role_session=FakeSession([]),
        resource_session=FakeSession([]),
        completer=completer,
        store=store,
    )
    app.dependency_overrides[get_pdp_service] = lambda: inner
    _override_authed_user()
    try:
        response = await client.post("/api/pdp", json={"career_goal": _ROLE})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "upload" in response.json()["detail"].lower()
    assert completer.calls_messages == []  # short-circuited before any LLM call
    assert store.saved == []  # nothing persisted


async def test_unmined_role_best_effort_pdf_with_status_header(client: httpx.AsyncClient) -> None:
    """Point 4: an unmined role still returns a best-effort PDF (200) stamped
    ``X-PDP-Status: role_profile_missing`` — a crash-free degrade, over the real chain."""
    store = InMemoryPdpStore()
    inner = _real_service(
        profile=_fixture_profile(),
        role_session=FakeSession([FakeExecuteResult([])]),  # role never mined
        resource_session=FakeSession([]),  # empty gap → no resource lookup
        completer=_RecordingSeqCompleter([_FULL_SECTIONS]),
        store=store,
    )
    app.dependency_overrides[get_pdp_service] = lambda: inner
    _override_authed_user()
    try:
        response = await client.post("/api/pdp", json={"career_goal": "Rare Role"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-pdp-status"] == "role_profile_missing"
    assert response.content.startswith(b"%PDF")
    assert len(store.saved) == 1


async def test_llm_outage_is_502_no_row_no_placeholder_pdf(client: httpx.AsyncClient) -> None:
    """Point 4: the P7-03 rev-2 fix stays intact — a total LLM outage (whose honest placeholder
    bodies would otherwise pass the length gate) surfaces as **502 with no persisted row**, never
    a silently-returned placeholder PDF. Driven through the real service chain end to end."""
    requirements = {"Python": {"frequency": 0.9, "weight": 1.0, "evidence": ["u1"]}}
    completer = _RaisingCompleter()
    store = InMemoryPdpStore()
    inner = _real_service(
        profile=_fixture_profile(),
        role_session=FakeSession([FakeExecuteResult([_role_profile_row(requirements)])]),
        resource_session=FakeSession([]),
        completer=completer,
        store=store,
    )
    app.dependency_overrides[get_pdp_service] = lambda: inner
    _override_authed_user()
    try:
        response = await client.post("/api/pdp", json={"career_goal": _ROLE})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert store.saved == []  # never persist a placeholder plan
    assert completer.calls == 2  # one initial try + one bounded retry, both raised
