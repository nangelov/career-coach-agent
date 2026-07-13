"""Skills-gap contract — user profile △ target ``role_profile`` (design §5.6, §5.2 / P7).

The stable, computed-not-persisted result of diffing a user's structured profile against a
target role's cached :class:`~app.repositories.models.market.RoleProfile`. This is the last
line of the market pipeline (§5.6: *"skills gap = user profile △ role_profile → feeds PDP"*)
and the **input contract** P7's PDP agent and P6-07's ``GET /api/roles/{role}/gap`` consume,
so it is a typed model (house style — cf. :mod:`app.schemas.jobs`), never a raw dict.

Two shapes in one result:

* :class:`SkillGap` — one *missing* required skill, carrying the role-required
  ``frequency`` / ``weight`` / ``evidence`` verbatim from the ``role_profile`` so the caller
  can rank and cite it (P7 ranks the PDP by exactly these). ``matched`` needs no such payload
  — a skill the user already has does not go into the plan — so it stays a plain skill list.
* :class:`SkillsGapResult` — the partition (``matched`` + ordered ``gap``) plus a
  :attr:`~SkillsGapResult.status` that lets a caller **degrade gracefully** instead of the
  service raising: a role that has never been mined, or a user with no parsed profile yet,
  both yield a clear "not available" outcome with ``gap=None`` (P6-07 decides whether to
  enqueue mining / prompt a CV upload — this layer never triggers either).

Matching is deliberately a normalized case-insensitive string compare (no embedding/fuzzy
matcher) — a documented simplification for this task; a smarter matcher can slot in behind
this same contract later without changing consumers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = ["SkillGap", "SkillsGapResult", "SkillsGapStatus"]

#: Outcome of a skills-gap request. ``ok`` — both inputs resolved and ``gap`` is populated
#: (possibly empty). ``profile_missing`` — the user has no parsed profile yet (upload a CV).
#: ``role_profile_missing`` — the target role has never been mined into a ``role_profiles``
#: row. Both "missing" states carry ``gap=None`` so P6-07 can branch without inspecting the
#: lists; this service never raises for them and never triggers mining itself (§5.6).
SkillsGapStatus = Literal["ok", "profile_missing", "role_profile_missing"]


class SkillGap(BaseModel):
    """One required skill the user's profile is **missing**, with its role-required weighting.

    ``frequency`` / ``weight`` / ``evidence`` are copied verbatim from the target
    ``role_profile``'s ``requirements[skill]`` entry (§5.6 — every requirement is cited), so
    P7's PDP can rank the gap (most in-demand first) and cite why each item matters.
    """

    skill: str = Field(..., description="The required skill the user does not yet have.")
    frequency: float = Field(
        default=0.0,
        description="How common this skill is across the role's evidence (0-1), from role_profile.",
    )
    weight: float = Field(
        default=0.0, description="The role_profile's importance weight for this skill."
    )
    evidence: list[Any] = Field(
        default_factory=list,
        description="Citations (job-posting ids / source urls) backing this requirement (§5.6).",
    )


class SkillsGapResult(BaseModel):
    """User profile △ target ``role_profile`` — the PDP's input contract (§5.6, §5.2 / P7).

    ``matched`` holds the required skills the user already has (plain names); ``gap`` holds the
    missing ones, **ordered most-in-demand first** (descending ``frequency`` then ``weight``).
    When :attr:`status` is not ``ok`` the inputs could not both be resolved and ``gap`` is
    ``None`` — the caller (P6-07) decides how to degrade.
    """

    role: str = Field(..., description="The target role the gap was computed against.")
    status: SkillsGapStatus = Field(
        default="ok", description="Whether both inputs resolved, or which one is unavailable."
    )
    matched: list[str] = Field(
        default_factory=list,
        description="Required skills the user already has (role's requirement names).",
    )
    gap: list[SkillGap] | None = Field(
        default=None,
        description=(
            "Missing required skills, most in-demand first — the PDP input. None when "
            "status != 'ok' (profile or role_profile unavailable)."
        ),
    )
