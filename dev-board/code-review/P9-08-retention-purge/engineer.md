# Engineer report — P9-08-retention-purge · Revision 1

## Summary
Added a **periodic** daily Celery job (S14, §6.18) that erases an SSO user's entire durable
footprint 30 days after their last activity, reusing the existing SEC-05 `delete_user` cascade —
no second delete path. "Last activity" is a computed `MAX(messages.created_at)` per user with a
`users.created_at` fallback (no new mutable column/migration). Registered on the repo's first
`beat_schedule`; added a `beat` service to `docker-compose.yml` so it fires locally. Guests are
untouched (Redis-only, TTL-expiring — P3-01/P9-07).

## Files changed
- `backend/app/repositories/retention.py` (new) — `RetentionRepository` port +
  `PostgresRetentionRepository`; one read-only grouped aggregate returning stale user ids.
- `backend/app/tasks/retention_purge.py` (new) — injectable core `run_retention_purge` (fakeable
  finder + eraser ports), worker composition-root `_purge_entrypoint`, and the
  `@celery_app.task tasks.retention_purge` body (mirrors `profile_ingest`'s sync→async bridge).
- `backend/app/tasks/celery_app.py` — added the task to `include`; added the daily `beat_schedule`
  (`crontab(hour=3, minute=0)`) — the repo's first periodic entry.
- `backend/app/config.py` — new `RETENTION_PURGE_AFTER_DAYS` setting (default 30, not hard-coded).
- `docker-compose.yml` — new `beat` service (same backend image, `celery ... beat`), mirroring
  `worker`.
- `backend/tests/test_retention_purge.py` (new) — unit tests of the core + registration/beat.
- `backend/tests/test_retention_purge_persistence.py` (new) — live-Postgres integration proof.

## Key decisions
- **"Last activity" definition (the crux):** `COALESCE(MAX(messages.created_at over the user's
  conversations), users.created_at)`, stale when strictly `<` the cutoff. Computed via LEFT JOINs
  + `GROUP BY … HAVING`; no denormalized `last_activity_at` column to keep in sync on every turn
  (per the task's explicit steer). `sessions.expires_at` was **deliberately excluded**: the
  Postgres `sessions` table is written lazily (Redis is the authoritative live-session registry),
  so it under-reports activity, and `expires_at` is a *future* timestamp (session lapse), not a
  moment of activity — an unreliable and semantically wrong activity proxy. Documented in
  `retention.py`.
- **Reuse `delete_user`, don't re-implement:** the purge feeds each stale id back through
  `PostgresAccountRepository.delete_user` (the Art. 17 cascade + feedback-contact scrub). Exactly
  one cascading-delete path remains. Redis session records for a 30-day-inactive user have already
  self-expired (TTL ≤ 24h), so there's nothing Redis-side to purge — noted in the task docstring.
- **No admin carve-out (deliberate):** `is_admin` is a plain flag on the same `users` row; §6
  item 26 / §6.18 name no admin retention exception, so the purge applies **uniformly** — an
  inactive admin is purged like anyone else. Stated explicitly in the task docstring so a reviewer
  can confirm it was a reading, not an oversight.
- **Best-effort sweep:** one user's `delete_user` failure is logged and skipped; the run continues
  and reports `{candidates, purged, failed, retention_days}`. Task-level failure (DB down)
  propagates → Celery `FAILURE`; the next daily run retries the whole idempotent sweep.
- **Daily granularity:** a 30-day window is coarse; `crontab(hour=3, minute=0)` (03:00 UTC,
  off-peak) easily satisfies it — no finer schedule needed.
- **P11/traces gap:** OTel export + retention is P11, not yet built; left a docstring TODO that
  P11's trace backend configures its own retention. This task scopes to the Postgres/Redis
  footprint that exists today.
- **HF Spaces (P12) note:** the single-container Dockerfile (P12, not built here) will need to run
  a `celery beat` process alongside the worker (e.g. via its process manager) for the schedule to
  fire in Spaces — flagged for P12, not attempted here.

## How to verify
- Unit: `cd backend && .venv/bin/python -m pytest tests/test_retention_purge.py -q`
- Live DB: `DATABASE_URL=postgresql+asyncpg://career_coach:<pw>@localhost:5432/career_coach \
  .venv/bin/python -m pytest tests/test_retention_purge_persistence.py -q`
- Schedule: `celery -A app.tasks.celery_app beat --loglevel=info` (or the compose `beat` service)
  enqueues `tasks.retention_purge` daily; the `worker` executes it.

## Tests (final step — mandatory)
- `pytest tests/test_retention_purge.py` → **9 passed**.
- `pytest tests/test_retention_purge_persistence.py` (live Postgres) → **2 passed** (finder
  boundary/fallback + full-footprint cascade vs. fresh-user survival).
- Full suite (`pytest -q`, live DB + Redis): **951 passed, 1 skipped** (unrelated ML-dep skip).
- `ruff check` (changed files) → All checks passed. `mypy` (new modules) → Success, no issues.
- No failing tests. No code/test defects to fix.

## Self-check
- [x] Meets acceptance criteria (stale query w/ boundary + fallback; daily beat; `delete_user`
      reuse; best-effort; docker `beat`; no admin exemption; unit + live-DB tests).
- [x] No secrets committed; Router→Service→Repository layering respected (read-only repo in the
      repository layer; task core depends only on structural ports, builds its own worker-local
      collaborators).
- [x] Tests/lints pass (pasted above).
