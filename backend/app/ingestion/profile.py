"""The structured CV/profile schema — the shape stored in ``profiles.data`` (§4).

This module owns the **canonical shape** of a parsed CV/profile: skills, experience,
education and career goals. It is the schema the P5-03 LLM-assisted structuring step
(:mod:`app.ingestion.structuring`) produces and — crucially — the exact JSON document the
P5-04 persistence step will write into the schema-less ``profiles.data`` JSONB column
(:class:`app.repositories.models.identity.Profile`, whose ``data`` column is intentionally
untyped at the DB layer so the shape can live here, in the ingestion/profile layer).

Design ref: app-design-and-features.md §5.1 (*"LLM-assisted parse → structured profile
(skills, experience, education, goals)"*) and §4 (``profiles.data`` JSONB).

**Graceful degradation is a first-class property (design §5.1).** Every field defaults to
empty (``[]`` / ``None``), so a partial CV — one with no education section, an experience
entry missing a company, no stated goals — validates into a profile with those parts left
empty rather than raising. A caller persists ``ProfileSchema.model_dump()`` straight into
``profiles.data``; the model is plain str/list only, so it is JSON-serializable as-is.

Dates are kept as free-text strings (e.g. ``"Jan 2020"``, ``"2019 - Present"``) rather than
typed dates on purpose: CV date formats are wildly inconsistent, and forcing them through a
strict date type would turn a messy-but-usable CV into a validation failure — the opposite
of the graceful-degradation requirement.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "EducationItem",
    "ExperienceItem",
    "ProfileSchema",
    "ProfileStructuringError",
]


class ProfileStructuringError(RuntimeError):
    """Structuring failed unrecoverably (bad LLM output the schema could not accept).

    A **single** typed error the caller (P5-04's Celery ingestion task) can catch: raised
    when the model returns no profile tool call, non-JSON / non-object arguments, or a
    payload that fails :class:`ProfileSchema` validation — as distinct from a merely
    *partial* CV, which degrades gracefully into empty fields and does **not** raise.
    """


class ExperienceItem(BaseModel):
    """One work-experience entry (a role held). All fields optional — see module docstring.

    ``title`` is the anchor of a role but is still optional: a partial entry recovered from
    a messy CV (e.g. a company and dates with an unreadable title) is kept rather than
    dropped, matching the graceful-degradation contract.
    """

    title: str | None = Field(default=None, description="Job title / role, e.g. 'Data Engineer'.")
    company: str | None = Field(default=None, description="Employer / organization name.")
    start_date: str | None = Field(
        default=None, description="Start of the role as written on the CV, e.g. 'Jan 2020'."
    )
    end_date: str | None = Field(
        default=None,
        description="End of the role as written, e.g. '2022' or 'Present' for a current role.",
    )
    description: str | None = Field(
        default=None, description="Summary of responsibilities and achievements in the role."
    )


class EducationItem(BaseModel):
    """One education entry. All fields optional — a partial entry is kept, not dropped."""

    institution: str | None = Field(
        default=None, description="School / university / awarding body name."
    )
    degree: str | None = Field(
        default=None, description="Qualification, e.g. 'BSc', 'MSc', 'PhD', 'Diploma'."
    )
    field: str | None = Field(
        default=None, description="Field of study / subject, e.g. 'Computer Science'."
    )
    start_date: str | None = Field(
        default=None, description="Start as written on the CV, e.g. '2015'."
    )
    end_date: str | None = Field(
        default=None, description="End / graduation as written, e.g. '2019' or 'Present'."
    )


class ProfileSchema(BaseModel):
    """A structured CV/profile — the document stored verbatim in ``profiles.data`` (§4).

    The four sections the design calls out (§5.1). Each defaults to empty, so a CV missing a
    section yields an empty list/field rather than an error. ``model_dump()`` produces the
    JSON-serializable dict the P5-04 persistence step writes into the ``profiles.data`` JSONB
    column.
    """

    skills: list[str] = Field(
        default_factory=list,
        description="Distinct skills, technologies and competencies mentioned in the CV.",
    )
    experience: list[ExperienceItem] = Field(
        default_factory=list, description="Work-experience entries, most recent first."
    )
    education: list[EducationItem] = Field(
        default_factory=list, description="Education / qualification entries."
    )
    goals: list[str] = Field(
        default_factory=list,
        description=(
            "Career goals or objectives stated in the CV (e.g. a summary/objective "
            "section). Empty when the CV states none — do not invent goals."
        ),
    )
