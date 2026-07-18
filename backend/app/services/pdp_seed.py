"""Seed the living-PDP dashboard from a generated plan (P8-04, §5.2).

A one-shot PDP PDF is only the *start* of a trackable plan: on a successful generation, the
concrete, actionable items the plan names are seeded into the caller's dashboard
(``goals``/``milestones``/``tasks``, P8-02's :class:`~app.services.dashboard.DashboardService`)
so the user can then track/approve/edit them (§5.2 *"Dashboard (living PDP)"*). This module owns
just that translation — the deterministic prose→rows extraction plus the goal reuse/de-dup rule —
so :class:`~app.services.pdp.PdpService` stays focused on generate → validate → render → persist
and simply calls :func:`seed_dashboard_from_pdp` after a success.

Two design anchors:

* **Attribution reuses P8-02 verbatim (§5.2).** Every seeded row is an AI-authored proposal, so
  the goal, milestones, and tasks are written with ``source="ai"`` — the service already resolves
  that to ``status="proposed"`` (pending user approval on the dashboard). Consistent with P8-03's
  tool-write posture: a plan the user asked to *generate* still means the AI *authored the specific
  items*, so they land as review-on-dashboard proposals, never silently active. This module never
  passes ``status`` itself.

* **Only the two action-item sections are seeded (task scope).** ``learning_objectives`` →
  milestones and ``timeline_action_steps`` → tasks are the two :class:`~app.schemas.pdp.PdpContent`
  sections that name concrete, actionable items. The assessment/reference sections
  (``current_skills_assessment`` / ``skills_gap_analysis`` / ``recommended_training`` /
  ``progress_tracking_kpis``) are *not* seeded. Items are extracted deterministically from the
  prose bullet/numbered lists (:func:`parse_line_items`) — never a second LLM pass, never invented
  content: a section that yields nothing parseable seeds no rows (the goal alone still lands).
"""

from __future__ import annotations

import re
from datetime import date

from app.schemas.dashboard import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    MilestoneCreate,
    TaskCreate,
)
from app.schemas.pdp import PdpContent
from app.services.dashboard import DashboardService

__all__ = ["parse_line_items", "seed_dashboard_from_pdp"]

#: Attribution every seeded row carries — the service resolves this to ``status="proposed"``
#: (pending approval, §5.2), exactly like P8-03's propose tools. Never pass ``status`` directly.
_AI_SOURCE = "ai"

#: The ``title`` column cap shared by goals/milestones/tasks (``schemas.dashboard``); a parsed
#: line item is truncated to it so an over-long bullet never raises at the create boundary.
_TITLE_MAX_LEN = 512

#: Cap on rows seeded from a single section — a defensive bound so a pathological plan (an LLM that
#: emits a 100-bullet list) cannot flood the dashboard with proposals. Well above any real plan's
#: item count; a plan that exceeds it is truncated rather than rejected.
_MAX_ITEMS_PER_SECTION = 25

#: A list line: a ``-``/``*``/``•`` bullet or a ``1.``/``1)`` numbered marker, then the item text.
#: Non-list prose (paragraphs, headings) does not match and is skipped.
_LIST_LINE_RE = re.compile(r"^(?:[-*•]|\d{1,3}[.)])\s+(?P<item>.*\S)\s*$")

#: A leading task-list checkbox (``[ ]`` / ``[x]``) left after the bullet marker is stripped.
_CHECKBOX_RE = re.compile(r"^\[[ xX]\]\s*")

#: Inline code spans — unwrap ``` `x` `` → ``x`` (keep the text, drop the backticks).
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")


def parse_line_items(text: str) -> list[str]:
    """Extract actionable line items from a markdown-ish prose section body (deterministic).

    Keeps only lines that are list items — a ``-``/``*``/``•`` bullet or a ``1.``/``1)`` numbered
    marker — and strips their markdown emphasis (``**bold**``, ``*italic*``, `` `code` ``) and any
    leading task-list checkbox, so each returned string is a clean, human-readable title. Prose
    paragraphs and headings (no list marker) are skipped; a section with no parseable list yields an
    empty list (the caller then seeds no rows rather than fabricating content). Blank items and
    exact duplicates within the section are dropped, and each item is truncated to the shared
    ``title`` column cap so a create never raises. The result is capped at
    :data:`_MAX_ITEMS_PER_SECTION`.
    """
    items: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        match = _LIST_LINE_RE.match(raw.strip())
        if match is None:
            continue
        cleaned = _clean_item(match.group("item"))
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
        if len(items) >= _MAX_ITEMS_PER_SECTION:
            break
    return items


def _clean_item(text: str) -> str:
    """Strip markdown emphasis + a leading checkbox from one list item and cap its length.

    Unwraps inline code, drops ``*`` emphasis markers (bold/italic) entirely, and strips a
    ``__bold__`` wrapper plus any stray surrounding ``_``/`` ` ``. Interior underscores are kept so
    a ``snake_case`` term survives. The result is capped to the shared ``title`` column length.
    """
    text = _CHECKBOX_RE.sub("", text.strip())
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = text.replace("*", "").replace("__", "")
    text = text.strip().strip("_`").strip()
    return text[:_TITLE_MAX_LEN].strip()


async def seed_dashboard_from_pdp(
    service: DashboardService,
    *,
    user_id: str,
    career_goal: str,
    target_date: date | None,
    content: PdpContent,
) -> None:
    """Seed one AI-``proposed`` goal + parsed milestones/tasks from ``content`` (§5.2).

    Reuses (or creates) a single goal for ``career_goal`` (see :func:`_reuse_or_create_goal`), then
    seeds milestones from ``learning_objectives`` and tasks from ``timeline_action_steps`` — the two
    action-item sections — adding only items not already present by title (case-insensitive), so a
    *regeneration* against the same goal never spams duplicate rows. All writes are ``source="ai"``.
    Raises nothing of its own beyond what the store surfaces — the caller runs this fail-soft so a
    dashboard hiccup never fails the PDF response.
    """
    goal = await _reuse_or_create_goal(service, user_id, career_goal, target_date)
    await _seed_milestones(service, user_id, goal.id, parse_line_items(content.learning_objectives))
    await _seed_tasks(service, user_id, goal.id, parse_line_items(content.timeline_action_steps))


async def _reuse_or_create_goal(
    service: DashboardService, user_id: str, career_goal: str, target_date: date | None
) -> GoalResponse:
    """Reuse a matching non-abandoned goal (de-dup rule) or create a fresh AI-proposed one.

    De-dup rule (task §"Regeneration must not spam duplicates"): ``pdps`` rows are append-only, but
    the dashboard is not — regenerating a plan for the *same* career goal must not create a second
    goal. So we look for the caller's existing goal whose ``title`` **or** ``target_role`` equals
    the career goal case-insensitively and is not ``abandoned``; if found, reuse it (refreshing its
    ``target_date`` when a new one is given) and only add *new* milestones/tasks below. This is a
    deliberate exact (case-insensitive) match — simple and testable — not a fuzzy matcher.
    """
    match = _find_matching_goal(await service.list_goals(user_id), career_goal)
    if match is not None:
        if target_date is not None and match.target_date != target_date:
            refreshed = await service.update_goal(
                user_id, match.id, GoalUpdate(target_date=target_date)
            )
            return refreshed if refreshed is not None else match
        return match
    return await service.create_goal(
        user_id,
        GoalCreate(title=career_goal, target_role=career_goal, target_date=target_date),
        source=_AI_SOURCE,
    )


def _find_matching_goal(goals: list[GoalResponse], career_goal: str) -> GoalResponse | None:
    """First non-abandoned goal whose title or target_role case-insensitively equals the goal."""
    key = career_goal.strip().casefold()
    for goal in goals:
        if goal.status == "abandoned":
            continue
        if (goal.title or "").strip().casefold() == key or (
            goal.target_role or ""
        ).strip().casefold() == key:
            return goal
    return None


async def _seed_milestones(
    service: DashboardService, user_id: str, goal_id: str, titles: list[str]
) -> None:
    """Create each new milestone under the goal (skipping titles already present)."""
    existing = await service.list_milestones(user_id, goal_id) or []
    present = {m.title.strip().casefold() for m in existing}
    for title in titles:
        if title.strip().casefold() in present:
            continue
        present.add(title.strip().casefold())
        await service.create_milestone(
            user_id, goal_id, MilestoneCreate(title=title), source=_AI_SOURCE
        )


async def _seed_tasks(
    service: DashboardService, user_id: str, goal_id: str, titles: list[str]
) -> None:
    """Create each new task under the goal (skipping titles already present)."""
    existing = await service.list_tasks(user_id, goal_id)
    present = {t.title.strip().casefold() for t in existing}
    for title in titles:
        if title.strip().casefold() in present:
            continue
        present.add(title.strip().casefold())
        await service.create_task(
            user_id, TaskCreate(goal_id=goal_id, title=title), source=_AI_SOURCE
        )
