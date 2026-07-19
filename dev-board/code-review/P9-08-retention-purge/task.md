# Task P9-08-retention-purge — S14: periodic retention purge (30 days after last activity)
- **Phase:** P9   **Status:** ENG   **Tags:** (B) — security item **S14**

## Scope
A **periodic** Celery job that deletes an SSO user's entire footprint (conversations, CVs/
profiles, learned memories, preferences, PDPs/dashboard, traces) **30 days after their last
activity**. Guests need no purge job — their data is already Redis-only and dies with the
session TTL (P3-01/P9-07).

From `dev-board/tasks.md` (P9):
> **S14 — Retention purge** (§6.18): periodic Celery job deleting SSO users' conversations /
> CVs / profiles / memories / traces **30 days after last activity**; guests expire with the
> session TTL.

### What already exists (read before building)
- `backend/app/repositories/account.py::PostgresAccountRepository.delete_user(user_id)` — the
  **existing** cascading-delete primitive built for `DELETE /api/me` (Art. 17 erasure, SEC-05).
  Every user-owned table's FK is `ON DELETE CASCADE` off `users.id` (except `feedback`, which
  is scrubbed not cascaded — already handled inside `delete_user`). **Reuse this exact method**
  for the purge — do not write a second cascading-delete path; the purge is "the same erasure,
  triggered by inactivity instead of a user's own request."
- **No `last_activity` column exists yet.** Derive "last activity" from real usage: the most
  recent `messages.created_at` across the user's conversations (join `messages` →
  `conversations` → filter `user_id`), falling back to `users.created_at` for a user who signed
  up but never sent a message. (If you find a cheaper/more-correct signal already computable
  from existing columns — e.g. also considering `sessions.expires_at` — use your judgement, but
  document the exact definition in `engineer.md` since it's the crux of this task.) Add a
  read-only repository query for "user ids whose last activity is older than N days" — do not
  add a new mutable column/migration unless a computed query proves impractical (a computed
  `MAX(messages.created_at)` per user, filtered, should be entirely practical at this scale —
  prefer that over a denormalized `last_activity_at` column that must be kept in sync
  everywhere a turn is persisted).
- `backend/app/tasks/celery_app.py` — the Celery app; **no periodic (beat) schedule exists in
  this repo yet** — this is the first one. Add a `beat_schedule` entry (Celery's built-in
  periodic-task scheduler) running the purge task once a day (a purge granularity of "once
  daily" easily satisfies a 30-day retention window — no need for finer scheduling).
- `docker-compose.yml` — the `worker` service is the pattern to mirror for a **new `beat`
  service** (same backend image, command `celery -A app.tasks.celery_app beat --loglevel=info`)
  so the schedule actually fires locally; wire it the same way (`env_file`, `DATABASE_URL`/
  `REDIS_URL` overrides, `depends_on: db/redis healthy`). Check whether the HF Spaces
  single-container Dockerfile (P12, not yet built) needs anything — note it in `engineer.md` if
  relevant, but do not attempt to build the P12 container here.
- `backend/app/tasks/profile_ingest.py` — the Celery-task pattern (sync task, `asyncio.run`
  bridge, worker constructs its own DB/embedder/router, heavy imports deferred) to mirror for
  the purge task's implementation.
- **Traces** — OpenTelemetry export/retention is **P11**, not yet built; do not invent a traces
  store here. Scope the "traces" part of this task to: leave a clear TODO/note in the purge
  task's docstring that P11's trace backend will need its own retention config (most OTel
  backends have their own retention setting) — this task's job is the **Postgres/Redis**
  footprint, which is what already exists.

## Acceptance criteria
- [ ] A repository query returning the set of user ids whose last activity (as defined above)
      is older than a configurable window (default 30 days, a new `RETENTION_DAYS` /
      `RETENTION_PURGE_AFTER_DAYS`-style setting in `config.py`, not a hard-coded literal).
- [ ] A Celery task that: fetches that set, and for each user id calls the existing
      `delete_user` cascade (batched/looped; do not need bulk-SQL cleverness — correctness over
      throughput at this scale). Logs a count of purged users; a single user's delete failure
      does not abort the whole run (log + continue).
- [ ] Registered on a **daily** `beat_schedule` entry in `celery_app.py`.
- [ ] `docker-compose.yml` gets a `beat` service so the schedule actually runs locally.
- [ ] `is_admin` users are **not** exempted — the design does not carve out an exception, and
      admin is just an app-level flag on the same `users` row (§6 item 26 — no special admin
      data-retention carve-out mentioned anywhere); purge applies uniformly. State this
      explicitly in `engineer.md` so a reviewer can confirm it was a deliberate reading, not an
      oversight.
- [ ] Unit tests: the "older than N days" query correctly includes/excludes users at the
      boundary (fake clock or explicit timestamps); the purge task calls `delete_user` for every
      stale user id and skips fresh ones; a delete failure for one user doesn't stop the batch.
- [ ] Integration test (or clearly documented manual steps) against a real Postgres proving a
      seeded stale user's full footprint (conversation/message, profile, preference, memory,
      dashboard rows) is gone after the purge task runs, while a fresh user's data survives.

## Design references
- dev-board/app-design-and-features.md: §6.18 "Retention → SSO users: 1 month. Guests: session
  only. [DECIDED]"; §7.6 privacy/retention section.
- dev-board/plan.md: P9.
- `backend/app/repositories/account.py` (`delete_user` — the SEC-05 erasure this task reuses).

## Constraints / non-goals
- No change to `DELETE /api/me` / `GET /api/me/export` (SEC-05) beyond reusing `delete_user`
  read-only — this task is purely a new caller of that existing primitive.
- No OTel/traces implementation — P11's job; note the gap, don't build it.
- No change to guest expiry (P3-01/P9-07 already handle it via Redis TTL).
- No frontend changes.
