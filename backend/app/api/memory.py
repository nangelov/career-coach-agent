"""Memory-panel API — view/edit preferences + view/delete learned memories (P9-05, §5.4 / §9).

The thin router (Router → Service → Repository, §8) for the "what the coach knows about you"
surface: it owns HTTP concerns only — auth gating, path/body shaping, and mapping the
:class:`~app.services.memory.MemoryService` outcomes onto status codes — and delegates all
business logic to the injected service.

**Auth required, guests rejected (``403``).** Learned memory and explicit preferences are
durable-only (§5.4 / §5.4 point durable store) — a guest has no ``user_memories``/``preferences``
row to view or edit, so a guest (``user_id=None``) is a ``403`` before any work
(:func:`_require_user`, mirroring ``dashboard``). Guest, session-only personalization is P9-07.

**Everything is scoped to the caller.** The owner is always the verified token subject — there is
no path/body ``user_id`` a caller could point at another user's data (§7 AuthZ). A memory id that
is unknown *or* belongs to another user reads as a uniform ``404`` (the service returns ``False``)
rather than leaking another user's data.

**No per-fact confirmation workflow (§6.10).** Preference edits and memory deletions are
immediate — this is the opt-out (silent-but-viewable/deletable) control surface, deliberately
*not* the propose/approve model P8-03's dashboard uses.

Dependency wiring is lazy: the service is assembled by the composition root (:mod:`app.bootstrap`)
on first use and cached on ``app.state``. Tests override :func:`get_memory_service` (and the auth
dependency) to inject fakes so no real Postgres wiring runs in unit tests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.app_state import AppStateKeys
from app.bootstrap import build_memory_service
from app.schemas.auth import CurrentUser
from app.schemas.memory import ClearMemoriesResponse, MemoryView, Preferences
from app.security.dependencies import require_auth
from app.services.memory import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_memory_service(request: Request) -> MemoryService:
    """FastAPI dependency: the app-scoped :class:`MemoryService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_memory_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a service
    over in-memory stores so the real Postgres wiring never runs in unit tests.
    """
    service: MemoryService | None = getattr(request.app.state, AppStateKeys.MEMORY_SERVICE, None)
    if service is None:
        service = build_memory_service(request.app)
        setattr(request.app.state, AppStateKeys.MEMORY_SERVICE, service)
    return service


def _require_user(current_user: CurrentUser) -> str:
    """Return the caller's ``user_id`` or reject a guest with ``403`` (durable-only surface)."""
    if current_user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memory requires an account. Sign in to view and manage what the coach knows.",
        )
    return current_user.user_id


@router.get("")
async def get_memory(
    current_user: CurrentUser = Depends(require_auth),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryView:
    """Return the caller's explicit preferences and their learned memories (§5.4)."""
    return await service.view(_require_user(current_user))


@router.put("/preferences")
async def put_preferences(
    payload: Preferences,
    current_user: CurrentUser = Depends(require_auth),
    service: MemoryService = Depends(get_memory_service),
) -> Preferences:
    """Replace the caller's explicit preferences with a validated body (§5.4) — immediate."""
    return await service.update_preferences(_require_user(current_user), payload)


@router.delete("", status_code=status.HTTP_200_OK)
async def clear_memories(
    current_user: CurrentUser = Depends(require_auth),
    service: MemoryService = Depends(get_memory_service),
) -> ClearMemoriesResponse:
    """Forget **all** the caller's learned memories (preferences untouched, §6.10)."""
    deleted = await service.clear_memories(_require_user(current_user))
    return ClearMemoriesResponse(deleted=deleted)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: CurrentUser = Depends(require_auth),
    service: MemoryService = Depends(get_memory_service),
) -> None:
    """Delete one learned memory, scoped to the caller (unknown/not-owned → ``404``)."""
    if not await service.delete_memory(_require_user(current_user), memory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
