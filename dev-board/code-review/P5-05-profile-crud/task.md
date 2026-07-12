# Task P5-05-profile-crud — GET/PUT /api/profile
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "`GET/PUT /api/profile`; reuse profile across chats (no re-upload)."

Add read/update access to the structured profile produced by `P5-04-cv-upload-endpoint`'s Celery task
(`profiles.data` JSONB, `app/repositories/models/identity.py::Profile`, one row per user, `unique=True` on
`user_id`), so the frontend (P5-07) and other agents can read/edit the profile **without re-uploading a CV**
(design §4/§8, API table line 398).

- `GET /api/profile` — return the authenticated user's structured profile (the `ProfileSchema` shape defined
  in `app/ingestion/profile.py`, P5-03). If no profile exists yet (never uploaded a CV), return a sensible
  "empty"/`404` response — pick one and document it clearly (a `404` is more RESTful for "no profile yet";
  an empty-but-200 body is friendlier for a frontend that always wants to render *something* — decide and
  justify briefly in your report).
- `PUT /api/profile` — replace/update the authenticated user's profile with a client-supplied body validated
  against `ProfileSchema` (or a dedicated request DTO in `app/schemas/profile.py` that maps onto it). This is
  how a user manually edits the auto-parsed profile (P5-07's "profile view/edit" UI will call this).
- Both endpoints are **auth-required** (`require_auth`, same as `POST /api/profile/cv`) and **user-scoped**:
  a user only ever reads/writes their **own** `profiles` row (§7 AuthZ — no path/query `user_id`, always the
  verified token subject, matching the posture in `profile_ingest.py`'s `submit`).
- Add a **repository adapter** (e.g. `app/repositories/profile_store.py`, mirroring
  `app/repositories/user_store.py`'s port/adapter shape: a narrow `ProfileStore` port the service depends on,
  a Postgres-backed implementation using the shared `PostgresConnectionProvider`) for the get/upsert against
  the `profiles` table — do not have the router or a service touch SQLAlchemy/the ORM model directly.
- Guests (`user_id=None`, per P5-04's documented decision that guests get no persisted profile): both
  endpoints should behave sensibly for a guest token — most likely `GET` returns "no profile" (same as a
  fresh account) and `PUT` is rejected (e.g. `403`/`409` with a clear reason) since there is no `users` row to
  anchor a guest's profile (mirrors the FK reality documented in `P5-04-cv-upload-endpoint/engineer.md`).
  Confirm and document the exact behavior you choose.
- Unit tests: get-with-no-profile, get-with-profile, put-creates, put-updates-existing, cross-user isolation
  (user A cannot read/write user B's profile), guest behavior, and validation-rejects-malformed-body.

## Acceptance criteria
- [ ] `GET /api/profile` returns the caller's own structured profile (or a documented "no profile yet"
      response) — never another user's.
- [ ] `PUT /api/profile` validates the body against the profile schema and upserts the caller's own `profiles`
      row — never another user's, and rejects malformed bodies with `422`/`400`.
- [ ] Both endpoints are behind `require_auth`; guest behavior is defined and tested (not left to fall through
      to a 500).
- [ ] A `ProfileStore` port + Postgres adapter exist in the repository layer; router/service never touch
      SQLAlchemy/the ORM directly (Router → Service → Repository, §8).
- [ ] Cross-user access is denied (existing AuthZ posture, §7 — mirror the pattern already established in P3).
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass (add a live-DB-gated integration test for the real
      Postgres round-trip, following the P2/P5 `importorskip`/live-DB convention — it may skip without a live
      Postgres).

## Design references
- dev-board/plan.md: Phase 5 (line 100)
- dev-board/app-design-and-features.md: §4 (`profiles` JSONB, line 146), §8 API table
  (`GET/PUT /api/profile`, line 398 — "Read/update structured profile | new"), §7 AuthZ ("users can only read
  their own... profiles").
- `backend/app/repositories/models/identity.py::Profile` — the target table.
- `backend/app/repositories/user_store.py` — the port/adapter pattern to mirror for a `ProfileStore`.
- `backend/app/api/profile.py`, `backend/app/services/profile_ingest.py`,
  `backend/app/ingestion/profile.py::ProfileSchema` — the existing profile router/schema this task extends
  (add `GET`/`PUT` handlers to the same `router` in `app/api/profile.py`; do not create a second router for
  the same resource unless there's a strong reason).
- `backend/app/security/dependencies.py` (`require_auth`) — existing auth dependency to reuse.

## Constraints / non-goals
- No CV upload/parsing changes — P5-04 is done; this task only adds read/write of the already-stored profile.
- No frontend work — P5-07 will call these endpoints.
- No `GET /api/jobs/status/{task_id}` — P5-06.
- Keep the profile schema authoritative in `app/ingestion/profile.py::ProfileSchema` (P5-03) — do not
  redefine a parallel shape unless a thin request/response DTO is genuinely needed at the API boundary
  (document why, if so).
