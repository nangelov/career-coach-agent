"""Dashboard API — CRUD goals/milestones/tasks + progress + summary (P8-02, §5.2 / §9).

The thin router (Router → Service → Repository, §8) for the ``/api/dashboard`` surface: it owns
HTTP concerns only — auth gating, path/body shaping, and mapping the
:class:`~app.services.dashboard.DashboardService` outcomes onto status codes — and delegates all
business logic to the injected service.

**Auth required, guests rejected (``403``).** The dashboard is the *persistent* living PDP, which
only logged-in users have (§5.2 *"Guests: dashboard requires an account"*). A guest
(``user_id=None``) is a ``403`` before any work is done; :func:`_require_user` centralizes the gate.

**Every write is scoped to the caller and stamped ``source="user"``.** The owner is always the
verified token subject — there is no path/body ``user_id`` a caller could point at another user's
data (§7 AuthZ, mirroring ``profile.py`` / ``pdp.py``). ``source`` is fixed to ``"user"`` here (the
service default); the ``source="ai"`` path is reserved for P8-03's native tools inside the agent
graph, not exposed through this human-facing router. A row the caller does not own reads as
``404`` (the service returns ``None``) rather than leaking another user's data.

Dependency wiring is lazy: the service is assembled by the composition root (:mod:`app.bootstrap`)
on first use and cached on ``app.state``. Tests override :func:`get_dashboard_service` (and the auth
dependency) to inject fakes so no real Postgres wiring runs in unit tests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.app_state import AppStateKeys
from app.bootstrap import build_dashboard_service
from app.schemas.auth import CurrentUser
from app.schemas.dashboard import (
    DashboardSummary,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    ProgressEntryCreate,
    ProgressEntryResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from app.security.dependencies import require_auth
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

#: Bounds for the ``GET /api/dashboard/progress`` page size (append-only log can grow large).
_MAX_PROGRESS_PAGE = 200


def get_dashboard_service(request: Request) -> DashboardService:
    """FastAPI dependency: the app-scoped :class:`DashboardService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_dashboard_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a service
    over an in-memory store so the real Postgres wiring never runs in unit tests.
    """
    service: DashboardService | None = getattr(
        request.app.state, AppStateKeys.DASHBOARD_SERVICE, None
    )
    if service is None:
        service = build_dashboard_service(request.app)
        setattr(request.app.state, AppStateKeys.DASHBOARD_SERVICE, service)
    return service


def _require_user(current_user: CurrentUser) -> str:
    """Return the caller's ``user_id`` or reject a guest with ``403`` (§5.2 — needs an account)."""
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The dashboard requires an account. Sign in to create and save your plan.",
        )
    return current_user.user_id


def _not_found(entity: str) -> HTTPException:
    """A uniform ``404`` for a missing/not-owned row (never distinguishes the two — no leak)."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found.")


# --------------------------------------------------------------------------- summary
@router.get("")
async def get_dashboard(
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardSummary:
    """Return the caller's goals (with nested milestones + tasks) and a progress/streak summary."""
    user_id = _require_user(current_user)
    return await service.get_summary(user_id)


# ----------------------------------------------------------------------------- goals
@router.get("/goals")
async def list_goals(
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[GoalResponse]:
    return await service.list_goals(_require_user(current_user))


@router.post("/goals", status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> GoalResponse:
    return await service.create_goal(_require_user(current_user), payload)


@router.get("/goals/{goal_id}")
async def get_goal(
    goal_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> GoalResponse:
    goal = await service.get_goal(_require_user(current_user), goal_id)
    if goal is None:
        raise _not_found("Goal")
    return goal


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> GoalResponse:
    goal = await service.update_goal(_require_user(current_user), goal_id, payload)
    if goal is None:
        raise _not_found("Goal")
    return goal


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> None:
    if not await service.delete_goal(_require_user(current_user), goal_id):
        raise _not_found("Goal")


# ------------------------------------------------------------------------- milestones
@router.get("/goals/{goal_id}/milestones")
async def list_milestones(
    goal_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[MilestoneResponse]:
    milestones = await service.list_milestones(_require_user(current_user), goal_id)
    if milestones is None:
        raise _not_found("Goal")
    return milestones


@router.post("/goals/{goal_id}/milestones", status_code=status.HTTP_201_CREATED)
async def create_milestone(
    goal_id: str,
    payload: MilestoneCreate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> MilestoneResponse:
    milestone = await service.create_milestone(_require_user(current_user), goal_id, payload)
    if milestone is None:
        raise _not_found("Goal")
    return milestone


@router.patch("/milestones/{milestone_id}")
async def update_milestone(
    milestone_id: str,
    payload: MilestoneUpdate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> MilestoneResponse:
    milestone = await service.update_milestone(_require_user(current_user), milestone_id, payload)
    if milestone is None:
        raise _not_found("Milestone")
    return milestone


@router.delete("/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone(
    milestone_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> None:
    if not await service.delete_milestone(_require_user(current_user), milestone_id):
        raise _not_found("Milestone")


# ---------------------------------------------------------------------------- tasks
@router.get("/tasks")
async def list_tasks(
    goal_id: str | None = Query(default=None, description="Optional filter to one goal's tasks."),
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[TaskResponse]:
    return await service.list_tasks(_require_user(current_user), goal_id)


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> TaskResponse:
    task = await service.create_task(_require_user(current_user), payload)
    if task is None:
        # The referenced goal (or milestone) is missing / not the caller's.
        raise _not_found("Goal or milestone")
    return task


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> TaskResponse:
    task = await service.get_task(_require_user(current_user), task_id)
    if task is None:
        raise _not_found("Task")
    return task


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> TaskResponse:
    task = await service.update_task(_require_user(current_user), task_id, payload)
    if task is None:
        raise _not_found("Task or milestone")
    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> None:
    if not await service.delete_task(_require_user(current_user), task_id):
        raise _not_found("Task")


# ------------------------------------------------------------------------- progress
@router.post("/progress", status_code=status.HTTP_201_CREATED)
async def add_progress(
    payload: ProgressEntryCreate,
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> ProgressEntryResponse:
    entry = await service.add_progress(_require_user(current_user), payload)
    if entry is None:
        # A referenced goal/task is missing / not the caller's.
        raise _not_found("Goal or task")
    return entry


@router.get("/progress")
async def list_progress(
    limit: int = Query(default=50, ge=1, le=_MAX_PROGRESS_PAGE),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_auth),
    service: DashboardService = Depends(get_dashboard_service),
) -> list[ProgressEntryResponse]:
    return await service.list_progress(_require_user(current_user), limit=limit, offset=offset)
