"""Account API — GDPR erasure + export (SEC-05, §7.6 / §9).

A deliberately **thin** router (Router → Service → Repository, §8): it owns HTTP concerns only
— authN gating, guest rejection, and response shaping — and delegates the two-store erasure and
the scoped export to :class:`~app.services.account.AccountService`. It serves the ``/api/me``
surface:

* ``DELETE /api/me`` — right to erasure (Art. 17). Revokes **all** of the caller's live Redis
  sessions (every device, not just this request's) and deletes their Postgres footprint via the
  cascade. Idempotent; returns ``204 No Content``.
* ``GET /api/me/export`` — portability (Art. 20). Returns the caller's complete own-data export
  as a downloadable JSON document (``Content-Disposition: attachment``), excluding raw embedding
  vectors and never leaking another user's or shared/curated rows.

**Logged-in users only.** A guest (``user_id=None``) has nothing durable to erase or export —
their only state is a Redis session record that self-expires on TTL (§4/§6.18) — so a guest is
rejected with ``403`` (consistent with ``PUT /api/profile``'s guest posture). Both endpoints
are user-scoped by construction (§7 AuthZ): the target is always the verified token subject;
there is no path/query/body ``user_id`` a caller could point at another account.

Dependency wiring is lazy: the service is assembled by the composition root (:mod:`app.bootstrap`)
on first use and cached on ``app.state``. Tests override :func:`get_account_service` to inject a
fake so no real Postgres/Redis wiring runs in unit tests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.app_state import AppStateKeys
from app.bootstrap import build_account_service
from app.schemas.account import AccountExport
from app.schemas.auth import CurrentUser
from app.security.dependencies import require_auth
from app.services.account import AccountService

router = APIRouter(prefix="/api/me", tags=["account"])

#: Rejection for a guest — no durable account exists to erase or export (§7.6).
_GUEST_DETAIL = "Guests have no account. Sign in to erase or export your data."


def get_account_service(request: Request) -> AccountService:
    """FastAPI dependency: the app-scoped :class:`AccountService`, built once and cached.

    Delegates construction to the composition root (:func:`app.bootstrap.build_account_service`)
    and caches the singleton on ``app.state``. Tests override this dependency to inject a fake so
    the real Postgres/Redis wiring never runs in unit tests.
    """
    service: AccountService | None = getattr(request.app.state, AppStateKeys.ACCOUNT_SERVICE, None)
    if service is None:
        service = build_account_service(request.app)
        setattr(request.app.state, AppStateKeys.ACCOUNT_SERVICE, service)
    return service


def _require_user(current_user: CurrentUser) -> str:
    """Return the caller's ``users.id`` or raise ``403`` for a guest (no durable account)."""
    if current_user.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_GUEST_DETAIL)
    return current_user.user_id


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: CurrentUser = Depends(require_auth),
    service: AccountService = Depends(get_account_service),
) -> None:
    """Erase the caller's account and all their data (Art. 17, §7.6) — logged-in users only.

    Requires a valid bearer token; a guest is rejected with ``403`` (nothing durable to erase).
    Revokes every one of the caller's live sessions (all devices) in Redis, then deletes their
    ``users`` row — which cascades their entire Postgres footprint. Idempotent (erasing an
    already-erased account is not an error); returns ``204``.
    """
    await service.erase(_require_user(current_user))


@router.get("/export")
async def export_me(
    response: Response,
    current_user: CurrentUser = Depends(require_auth),
    service: AccountService = Depends(get_account_service),
) -> AccountExport:
    """Return the caller's complete own-data export (Art. 20, §7.6) — logged-in users only.

    Requires a valid bearer token; a guest is rejected with ``403``. The export is strictly
    scoped to the caller's own rows and excludes raw embedding vectors. Served with a
    ``Content-Disposition: attachment`` header so the browser downloads it as a JSON file.
    """
    export = await service.export(_require_user(current_user))
    response.headers["Content-Disposition"] = 'attachment; filename="career-coach-export.json"'
    return export
