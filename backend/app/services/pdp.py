"""PDP service — stored profile → skills gap → PDP → validated PDF → persisted row (P7-03, §5.2).

The **policy** layer behind the thin ``POST /api/pdp`` route (Router → Service → Agent/Repository,
§8): it owns the PDP generation flow so the router stays HTTP-only. The v2 replacement for v1's
synchronous ``/pdp-generator`` — but instead of re-uploading and re-parsing a CV on every request,
it uses the caller's **stored** structured profile (P5), so regenerating a plan needs no upload
(§4 *"one structured CV/profile per user, reused across chats"*).

The flow (task acceptance):

1. Load the caller's stored profile (:class:`~app.services.profile_store.ProfileStore`). No
   profile → :class:`PdpProfileMissing` (the router maps it to a clear "upload a CV first"
   ``422`` — never a 500 or a broken PDF).
2. Compute the skills gap for the goal via the reused P6-05
   :class:`~app.services.skills_gap.SkillsGapService` (never recomputed here). An **unmined
   role degrades gracefully to a profile-only best-effort plan** (the P7-01 agent handles
   ``role_profile_missing``) rather than blocking on a 202 mine-and-poll round-trip — a PDP is
   a one-shot download the user asked for now, so the friendlier contract is to always return a
   usable plan when a profile exists. The unmined state is still surfaced (the plan's Skills Gap
   section says so, and the endpoint stamps ``X-PDP-Status``).
3. Generate the structured plan (:func:`~app.agents.pdp_agent.generate_pdp` — native
   tool-calling, no ReAct) and gate it. A **synthesis failure** (the agent returns
   ``status="generation_failed"`` because all LLMs were down / the tool call was unusable — its
   placeholder text would otherwise slip past the length gate) *or* a plan too thin for
   :func:`~app.pdf.validate_pdp_content` is retried **once** (mirrors v1's bounded
   ``max_retries``) then surfaced as :class:`PdpGenerationFailed` — never a broken/placeholder PDF
   and never a persisted row.
4. Render the styled PDF (:func:`~app.pdf.build_pdp_pdf`) and persist a ``pdps`` row
   (:class:`~app.services.pdp_store.PdpStore`) so the PDP is a first-class stored record.

**Synchronous, not Celery.** Unlike P5's CV parse (explicitly a background job — arbitrary file
sizes, OCR), the PDP is a single bounded-token LLM call over already-parsed data; ``plan.md`` /
``tasks.md`` do not call out Celery here, so the plan is generated in-request and the PDF returned
directly (v1's posture). If the LLM call ever routinely exceeds a reasonable request timeout, this
is the seam to move behind a task — the service body would not change, only its caller.

**Dependency injection (mirrors P6-07 / P4-03).** Built once by the composition root
(:func:`app.bootstrap.build_pdp_service`) from ports only — the profile store, the skills-gap
service, the PDP store, an :class:`~app.agents.planner.LLMCompleter` (the failover
:class:`~app.llm.router.LLMRouter`), and a :class:`~app.services.skills_gap.SessionProvider` (the
shared Postgres pool, handed to the agent for its learning-resource lookup) — so unit tests inject
fakes and no real HF/Postgres wiring runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from app.agents.pdp_agent import ResourceLookup, generate_pdp
from app.agents.planner import LLMCompleter
from app.pdf import build_pdp_pdf, validate_pdp_content
from app.schemas.pdp import PdpContent
from app.services.dashboard import DashboardService
from app.services.pdp_seed import seed_dashboard_from_pdp
from app.services.pdp_store import PdpStore
from app.services.profile_store import ProfileStore
from app.services.skills_gap import SkillsGapService

logger = logging.getLogger(__name__)

__all__ = [
    "PdpGenerated",
    "PdpGenerationFailed",
    "PdpProfileMissing",
    "PdpResult",
    "PdpService",
]

#: How many attempts to produce a plan that passes :func:`validate_pdp_content` — one initial
#: try plus one retry (mirrors v1's bounded ``max_retries`` around ``validate_pdp_response``).
_MAX_VALIDATION_ATTEMPTS = 2


@dataclass(frozen=True)
class PdpGenerated:
    """Success: a validated, styled PDF plus its persisted ``pdps`` row id and plan status.

    ``status`` is the P7-01 :attr:`~app.schemas.pdp.PdpContent.status` (``ok`` or
    ``role_profile_missing``) so the router can surface whether the role was mined without
    breaking the PDF stream.
    """

    pdf: bytes
    pdp_id: str
    status: str


@dataclass(frozen=True)
class PdpProfileMissing:
    """Degraded: the caller has no stored profile yet — the router prompts a CV upload (422)."""


@dataclass(frozen=True)
class PdpGenerationFailed:
    """Failure: the plan could not be made substantial enough after the bounded retry (502)."""


#: The discriminated outcome the router branches on (never a raised 500 for a known state).
PdpResult = PdpGenerated | PdpProfileMissing | PdpGenerationFailed


class PdpService:
    """Generate → validate → render → persist a PDP (Router → Service → Agent/Repository, §8).

    Depends only on ports: the profile store, the reused P6-05 skills-gap service, the PDP
    store, an :class:`LLMCompleter`, a :class:`ResourceLookup` (session provider), and the P8-02
    :class:`~app.services.dashboard.DashboardService` (to seed the living PDP after a success).
    Built once by the composition root (:func:`app.bootstrap.build_pdp_service`).
    """

    def __init__(
        self,
        *,
        profile_store: ProfileStore,
        skills_gap: SkillsGapService,
        pdp_store: PdpStore,
        router: LLMCompleter,
        db: ResourceLookup,
        dashboard: DashboardService,
    ) -> None:
        self._profile_store = profile_store
        self._skills_gap = skills_gap
        self._pdp_store = pdp_store
        self._router = router
        self._db = db
        self._dashboard = dashboard

    async def generate(
        self,
        *,
        user_id: str,
        career_goal: str,
        target_date: date | None,
        additional_context: str | None = None,
    ) -> PdpResult:
        """Run the full PDP flow for ``user_id``, degrading gracefully instead of raising.

        A missing profile short-circuits to :class:`PdpProfileMissing` before any LLM call; an
        unmined role still produces a best-effort plan (the agent's ``role_profile_missing``
        path). Each attempt is rejected if the agent reports ``status="generation_failed"`` (the
        LLM synthesis itself failed — its honest placeholder text would otherwise pass the length
        gate) *or* if the plan is too thin for :func:`validate_pdp_content`; both are retried once
        within the bounded budget, and a persistent failure returns :class:`PdpGenerationFailed`
        (no ``pdps`` row). On success the PDF is rendered and a ``pdps`` row persisted, returning
        :class:`PdpGenerated`.
        """
        profile = await self._profile_store.get(user_id)
        if profile is None:
            return PdpProfileMissing()

        # Reuse the P6-05 gap arithmetic (canonicalization is not applied here — an unmined
        # spelling simply degrades to a best-effort plan, keeping this service free of the
        # embedder/ML stack; the agent handles ``role_profile_missing``). This deliberately
        # re-reads the profile inside ``compute`` (a second, cheap indexed read) rather than
        # threading the already-loaded profile through the shared P6-05 ``compute`` signature —
        # keeping that service's contract (used by ``roles.py`` too) unchanged for one caller's
        # micro-optimization is not worth the coupling.
        skills_gap = await self._skills_gap.compute(user_id, career_goal)
        target_iso = target_date.isoformat() if target_date is not None else None
        goal_text = _effective_goal(career_goal, additional_context)

        content: PdpContent | None = None
        for attempt in range(_MAX_VALIDATION_ATTEMPTS):
            content = await generate_pdp(
                profile=profile,
                skills_gap=skills_gap,
                career_goal=goal_text,
                target_date=target_iso,
                router=self._router,
                db=self._db,
            )
            if content.status == "generation_failed":
                # The LLM synthesis itself failed (all models down / unusable tool call) — the
                # placeholder bodies would pass ``validate_pdp_content``, so we must not treat
                # them as a plan. Retry within the bounded budget, then surface a clear error.
                logger.warning(
                    "PDP synthesis failed (attempt %d/%d) for goal %r",
                    attempt + 1,
                    _MAX_VALIDATION_ATTEMPTS,
                    career_goal,
                )
                continue
            if validate_pdp_content(content):
                break
            logger.warning(
                "PDP failed validation (attempt %d/%d) for goal %r",
                attempt + 1,
                _MAX_VALIDATION_ATTEMPTS,
                career_goal,
            )
        else:
            # Exhausted the bounded retry without a substantial, successfully-synthesized plan —
            # a clear error, never a broken/placeholder PDF (mirrors v1's post-``max_retries``
            # failure). No ``pdps`` row is persisted.
            return PdpGenerationFailed()

        assert content is not None  # loop ran at least once
        pdf = build_pdp_pdf(content, career_goal, target_iso)
        pdp_id = await self._pdp_store.save(
            user_id=user_id,
            career_goal=career_goal,
            target_date=target_date,
            content=content,
        )
        await self._seed_dashboard(user_id, career_goal, target_date, content)
        return PdpGenerated(pdf=pdf, pdp_id=pdp_id, status=content.status)

    async def _seed_dashboard(
        self, user_id: str, career_goal: str, target_date: date | None, content: PdpContent
    ) -> None:
        """Seed the caller's living-PDP dashboard from the plan — **fail-soft** (P8-04, §5.2).

        Runs only after a successful generation, turning the one-shot plan into a trackable set of
        AI-``proposed`` goal/milestones/tasks (via
        :func:`app.services.pdp_seed.seed_dashboard_from_pdp`).
        The user's PDF download must never depend on dashboard availability, so any failure here
        (DB hiccup, etc.) is logged and swallowed — the PDF is still returned. Mirrors the fail-soft
        posture used throughout the agents/tools.
        """
        try:
            await seed_dashboard_from_pdp(
                self._dashboard,
                user_id=user_id,
                career_goal=career_goal,
                target_date=target_date,
                content=content,
            )
        except Exception:  # noqa: BLE001 - seeding must never fail the PDP response
            logger.exception("Failed to seed dashboard from PDP for user %s", user_id)


def _effective_goal(career_goal: str, additional_context: str | None) -> str:
    """Fold optional user context into the goal text handed to the agent's trusted turn.

    The stored ``pdps.career_goal`` keeps the raw goal; only the text the coach reasons over
    carries the extra context, so the persisted record stays a clean goal while the plan still
    reflects the user's constraints/preferences. The context is the authenticated user's own
    input (trusted), so it rides in the plain turn — not the fenced untrusted blocks.
    """
    goal = career_goal.strip()
    context = (additional_context or "").strip()
    if not context:
        return goal
    return f"{goal}. Additional context from me: {context}"
