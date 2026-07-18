"""PDP content contract — the structured Personal Development Plan (design §5.2 / P7).

The typed shape the P7-01 PDP agent produces and the P7-02 PDF builder / ``pdps.content``
JSONB column (:class:`~app.repositories.models.dashboard.Pdp`, already migrated in P2-05)
consume **without re-parsing markdown**. It is a structured model (house style — cf.
:mod:`app.schemas.skills_gap`), never a single opaque markdown blob (task constraint), so a
downstream consumer addresses each section by field.

Two design anchors:

* **The v1 six-section heading contract** (legacy ``pdp_query`` /
  ``validate_pdp_response``): the plan is exactly these six sections, in this order. Each is a
  field here; the canonical ``## <Heading>`` markers are added **deterministically** by
  :meth:`PdpContent.to_markdown` (the agent stores only section *bodies*, so a model can never
  emit a malformed/duplicated heading, and the rendered markdown always passes the P7-02
  validator — real ``##`` headings, no ReAct/tool-call scaffolding).
* **Grounded, not hallucinated recommendations** (§5.7): the concrete courses that back the
  *Recommended Training* section are carried structurally in :attr:`PdpContent.resources`
  (title + provider + URL, pulled from the shared learning-resource corpus by the agent), so
  P7-02 renders the real citation list rather than trusting free-text the model wrote.
* **Graceful degradation** (§5.1): :attr:`PdpContent.status` lets the caller (P7-03) tell a
  full plan from a best-effort one built without a mined role profile, or the "no profile yet"
  error — the agent never raises for these, it returns a clear status.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "SECTION_HEADINGS",
    "LearningResourceRef",
    "PdpContent",
    "PdpRequest",
    "PdpStatus",
]

#: Outcome of a PDP generation. ``ok`` — the plan was built from the profile *and* a mined
#: skills gap. ``role_profile_missing`` — the profile was present but the target role has not
#: been mined yet, so the plan is a best-effort one from the profile + goal alone (the gap and
#: cited resources are empty). ``profile_missing`` — no parsed profile exists yet (upload a CV);
#: no plan was generated. ``generation_failed`` — a profile existed but synthesis failed (all
#: LLMs down / an unusable tool call), so the section bodies are honest placeholders, *not* a
#: real plan; the caller (P7-03) must surface this as a generation error (502, no persisted row),
#: never return/store it as a plan. The agent never raises for any of these — P7-03 branches on
#: the status.
PdpStatus = Literal["ok", "role_profile_missing", "profile_missing", "generation_failed"]

#: The v1 six-section contract: ``(field_name, canonical_heading)`` in render order. The single
#: source of truth for both :meth:`PdpContent.to_markdown` (adds the ``## <Heading>`` markers)
#: and the ``record_pdp`` tool schema the agent forces (its properties mirror these fields), so
#: the section set cannot drift between the model and the LLM contract.
SECTION_HEADINGS: tuple[tuple[str, str], ...] = (
    ("current_skills_assessment", "Current Skills Assessment"),
    ("skills_gap_analysis", "Skills Gap Analysis"),
    ("learning_objectives", "Learning Objectives and Milestones"),
    ("recommended_training", "Recommended Training and Development"),
    ("timeline_action_steps", "Timeline and Action Steps"),
    ("progress_tracking_kpis", "Progress Tracking and KPIs"),
)


class PdpRequest(BaseModel):
    """The ``POST /api/pdp`` request body (P7-03, §9) — **no file upload**.

    The v2 endpoint uses the caller's *stored* structured profile (P5), so — unlike v1's
    ``/pdp-generator`` multipart upload — the request carries only the target ``career_goal``
    (which also names the role the skills gap is computed against), an optional ``target_date``
    for the plan's timeline, and optional free-text ``additional_context`` the user wants the
    coach to weigh. Regenerating a plan never requires re-uploading a CV.
    """

    career_goal: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="The target career goal / role the plan (and skills gap) is built for.",
    )
    target_date: date | None = Field(
        default=None,
        description="Optional target date the plan's timeline and milestones aim at.",
    )
    additional_context: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional free-text context (constraints, preferences) for the coach.",
    )


class LearningResourceRef(BaseModel):
    """One concrete, cited learning resource backing the *Recommended Training* section (§5.7).

    Pulled by the agent from the shared learning-resource corpus (never invented), so P7-02 can
    render a real citation (course title + provider + URL) deterministically instead of trusting
    free text the model wrote.
    """

    title: str = Field(..., description="The course / track title, as curated in the corpus.")
    provider: str | None = Field(default=None, description="The course provider, e.g. 'Coursera'.")
    url: str | None = Field(default=None, description="The canonical URL of the resource.")
    skills: list[str] = Field(
        default_factory=list,
        description="The gap skill(s) this resource was matched to (why it is recommended).",
    )


class PdpContent(BaseModel):
    """A structured Personal Development Plan — the six v1 sections + cited resources (§5.2).

    The shape stored in ``pdps.content`` (JSONB) and rendered to a styled PDF by P7-02.
    :meth:`to_markdown` renders the canonical ``## <Heading>`` document (the v1 contract the
    P7-02 validator gates on); section fields hold only the prose *body* of each section.
    """

    status: PdpStatus = Field(
        default="ok",
        description="Whether the plan is full, best-effort (no role profile), or absent (no CV).",
    )
    current_skills_assessment: str = Field(
        default="", description="Current Skills Assessment section body (from the profile)."
    )
    skills_gap_analysis: str = Field(
        default="", description="Skills Gap Analysis section body (from the ranked skills gap)."
    )
    learning_objectives: str = Field(
        default="", description="Learning Objectives and Milestones section body."
    )
    recommended_training: str = Field(
        default="",
        description="Recommended Training body (cites resources, never invents courses).",
    )
    timeline_action_steps: str = Field(
        default="", description="Timeline and Action Steps section body."
    )
    progress_tracking_kpis: str = Field(
        default="", description="Progress Tracking and KPIs section body."
    )
    resources: list[LearningResourceRef] = Field(
        default_factory=list,
        description="Concrete corpus resources cited by the Recommended Training section (§5.7).",
    )

    def to_markdown(self) -> str:
        """Render the six sections into the canonical ``## <Heading>`` markdown document.

        The headings and their order come from :data:`SECTION_HEADINGS` (the v1 contract), added
        here — not by the model — so the output always carries real ``##`` headings and never any
        ReAct/tool-call scaffolding, satisfying the P7-02 ``validate_pdp_response`` gate.
        """
        blocks: list[str] = []
        for field_name, heading in SECTION_HEADINGS:
            body = (getattr(self, field_name) or "").strip()
            blocks.append(f"## {heading}\n\n{body}" if body else f"## {heading}")
        return "\n\n".join(blocks)
