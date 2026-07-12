# Engineer report — P5-05-profile-crud · Revision 1

## Summary
Added `GET /api/profile` and `PUT /api/profile` so a user can read and manually edit the
structured profile the P5-04 Celery task parsed from their CV — reused across chats, no
re-upload (design §4/§8, API table line 398). Introduced a narrow `ProfileStore` port + a
Postgres adapter (mirroring the `UserStore`/`FeedbackReader` port/adapter idiom) so the router
never touches SQLAlchemy/the ORM directly (Router → Service → Repository, §8). Both endpoints
are `require_auth`-gated and strictly user-scoped (§7 AuthZ): the target row is always the
verified token subject's own — no path/query `user_id`.

## Files changed
- `app/services/profile_store.py` (new) — the `ProfileStore` port (ABC) + `InMemoryProfileStore`
  test double. Trades in the authoritative `app.ingestion.profile.ProfileSchema` (P5-03) rather
  than redefining a parallel API shape. `get` / `upsert`, keyed on `users.id`.
- `app/repositories/profile_store.py` (new) — `PostgresProfileStore`: `get` (indexed lookup,
  malformed id → `None` fail-safe, JSONB re-validated through `ProfileSchema`) and `upsert`
  (`INSERT ... ON CONFLICT (user_id) DO UPDATE`, one row per user, explicit `updated_at=now()`).
  All DB access via the shared `PostgresConnectionProvider` (§4).
- `app/api/profile.py` — added `get_profile_store` dependency (lazy build + cache on
  `app.state`), the `GET`/`PUT` handlers, and expanded the module docstring for the full
  `/api/profile` surface.
- `app/bootstrap.py` — `build_profile_store` (Postgres-required, fails loudly if the pool is
  missing — a profile is FK-anchored to a `users` row, cannot degrade to Redis-only).
- `app/app_state.py` — `AppStateKeys.PROFILE_STORE` cache key.
- `tests/test_profile_api.py` (new) — unit tests over `InMemoryProfileStore` + overridden
  `require_auth` (no real Postgres).
- `tests/test_profile_store_postgres.py` (new) — live-DB-gated integration round-trip
  (`importorskip`/reachability skip, per the P2/P5 convention).

## Key decisions
- **No-profile → empty `200`, not `404`** (task's documented choice). The P5-07 view/edit UI
  always wants a renderable shape, and `ProfileSchema` degrades gracefully to all-empty. Keeps
  `GET`/`PUT` symmetric (both speak `ProfileSchema`). A fresh account and a guest both read the
  same empty profile.
- **Reuse `ProfileSchema` as the wire contract** (no new DTO). The task says keep it
  authoritative and only add a DTO if genuinely needed; it is a clean pydantic model already
  persisted verbatim into `profiles.data`, so using it directly is DRY and means a read
  normalizes stored JSON through the same validation the parse produced it with. `services` →
  `ingestion` coupling is already an established pattern (`profile_ingest.py` imports
  `ingestion.formats`).
- **Guest `PUT` → `403`** (guest `GET` → empty `200`). A profile is FK-anchored to a `users`
  row; a guest has none, so there is nothing to persist against — mirrors the guest posture the
  P5-04 upload task documented. `403` with a sign-in message; nothing is written. Guest `GET`
  short-circuits to an empty profile without a DB lookup.
- **Atomic upsert via `ON CONFLICT (user_id)`** rather than SELECT-then-branch — no race, and
  the `unique` `user_id` guarantees exactly one row per user. `updated_at` set explicitly on the
  conflict path because the ORM `onupdate` hook does not fire for a Core `on_conflict_do_update`.
- **Malformed body → `422`** falls out of FastAPI validating the `ProfileSchema` body before the
  handler runs; the store is never reached.

## How to verify
- `ruff check . && ruff format --check . && mypy app`
- `python -m pytest tests/test_profile_api.py tests/test_profile_store_postgres.py -q`
- Live DB round-trip (optional): with docker-compose Postgres up + `alembic upgrade head`, the
  two `test_profile_store_postgres.py` tests run (otherwise they skip).

## Tests (final step — mandatory)
- `python -m pytest -q` → **389 passed, 47 skipped** in ~8s (skips are the live-DB / heavy-ML
  gated suites, including this task's 2 Postgres round-trip tests without a local DB).
- `ruff check .` → All checks passed · `ruff format --check .` → 150 files already formatted
- `mypy app` → Success: no issues found in 85 source files
- No failures to root-cause.

## Self-check
- [x] Meets acceptance criteria: `GET` returns caller's own profile (empty `200` when none);
  `PUT` validates (`422` on malformed) and upserts caller's own row; both behind `require_auth`;
  guest behavior defined + tested (GET empty, PUT `403`); `ProfileStore` port + Postgres adapter
  exist and the router/service never touch the ORM; cross-user isolation tested; live-DB test
  added.
- [x] No secrets committed; Router→Service→Repository layering respected (router depends only on
  the port; adapter is the only place SQLAlchemy is imported for this feature).
- [x] Tests/lints pass (output pasted above).
