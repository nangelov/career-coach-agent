"""Role-requirements API contracts (P6-07, §5.6 / §9) — the market surface's wire shapes.

The response models for ``GET /api/roles/{role}/requirements`` (design §9: *"replaces
`/api/jobs`; no listings"*). Kept independent of the agent/repository layers (house style —
cf. :mod:`app.schemas.jobs` / :mod:`app.schemas.skills_gap`): the router maps the cached
:class:`~app.repositories.models.market.RoleProfile` (and the mining job handle) onto these,
so the datastore shape never leaks to the client.

Two outcomes share this module:

* :class:`RoleRequirementsResponse` (HTTP 200) — the **cache-hit** body: the role's
  frequency-ranked, **cited** requirements plus the aggregation's ``evidence_count`` and
  ``refreshed_at`` staleness marker (§5.6 — *"every requirement carries citations"*).
* :class:`RoleMiningAccepted` (HTTP 202) — the **cache-miss** body: the async mine-job handle,
  the *same shape* P5-04's :class:`~app.schemas.profile.CvUploadResponse` established
  (``task_id`` + ``status="accepted"``), so the client polls the existing
  ``GET /api/jobs/status/{task_id}`` (P5-06) — one generic status endpoint, not a second one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RoleRequirement(BaseModel):
    """One ranked, cited requirement for a role (from ``role_profile.requirements[skill]``).

    ``frequency`` / ``weight`` / ``evidence`` are the aggregated market signal for this skill
    (§5.6 — every requirement is cited): ``evidence`` carries the job-posting ids / source urls
    backing it, so the client can show *why* the requirement matters.
    """

    skill: str = Field(..., description="The required skill.")
    frequency: float = Field(
        default=0.0,
        description="How common this skill is across the role's evidence (0-1).",
    )
    weight: float = Field(default=0.0, description="Aggregated importance weight for this skill.")
    evidence: list[Any] = Field(
        default_factory=list,
        description="Citations (job-posting ids / source urls) backing this requirement (§5.6).",
    )


class RoleRequirementsResponse(BaseModel):
    """``GET /api/roles/{role}/requirements`` (HTTP 200) — the cached role requirement profile.

    ``requirements`` is **frequency-ranked** (most in-demand first); ``evidence_count`` and
    ``refreshed_at`` expose how well-backed and how fresh the profile is (§5.6). ``role`` is the
    canonical role the request normalized to.
    """

    role: str = Field(..., description="The canonical role the requirements were resolved for.")
    requirements: list[RoleRequirement] = Field(
        default_factory=list,
        description="The role's requirements, most in-demand first (frequency-ranked, cited).",
    )
    evidence_count: int = Field(
        default=0,
        description="How many evidence items backed the aggregation (postings + taxonomy).",
    )
    refreshed_at: datetime | None = Field(
        default=None,
        description="When the profile was last mined (staleness marker); None if never refreshed.",
    )


class RoleMiningAccepted(BaseModel):
    """``GET /api/roles/{role}/requirements`` / ``/gap`` (HTTP 202) — the async mine-job handle.

    Returned when the role has never been mined (no ``role_profiles`` row): the request enqueues
    a background ``mine_role`` Celery job and returns immediately. Mirrors P5-04's
    :class:`~app.schemas.profile.CvUploadResponse` (``task_id`` + ``status="accepted"``) so the
    client polls the **existing** ``GET /api/jobs/status/{task_id}`` (P5-06).
    """

    task_id: str = Field(
        ..., description="Celery task id to poll for the mine job's progress (P5-06)."
    )
    status: Literal["accepted"] = Field(
        default="accepted",
        description="Always 'accepted' — the role mine job was enqueued.",
    )
