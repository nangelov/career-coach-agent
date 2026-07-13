# Task SEC-05-gdpr-erasure-export — GDPR erasure + export
- **Phase:** SEC   **Status:** ENG   **Tags:** (B)

## Scope
Implement `DELETE /api/me` (Art. 17 right to erasure) and `GET /api/me/export` (Art. 20
portability) per design §7.6 / §9 API surface. **Logged-in users only** (guests have nothing
durable to erase/export — everything is Redis session-TTL already).

### What already helps you
The P2 migrations already modeled this correctly — **every** user-owned table's `user_id` FK is
`ondelete="CASCADE"` (verified: `profiles`, `preferences`, `sessions`→`conversations`→`messages`
(cascade chain), `message_feedback`, `feedback`, `kb_documents` (user's private CV chunks),
`user_memories`, `pdps`, `goals`→`milestones`/`tasks` (cascade chain), `progress_entries`). So
**deleting the `users` row cascades the entire Postgres footprint** — you do not need to
hand-write per-table delete statements; a single `DELETE FROM users WHERE id = :user_id` (or the
SQLAlchemy equivalent via the existing `PostgresConnectionProvider`/repository pattern) does the
Postgres side.

### What you still need to build
1. **Redis session invalidation across all the user's active sessions.** The live JWT-validity
   check (`SessionAuthenticator.authenticate`, `backend/app/services/auth.py`) reads
   `SessionStore.get(session_id)` (Redis-backed via `RedisSessionStore`,
   `backend/app/repositories/redis.py`) — deleting the Postgres `users`/`sessions` rows does
   **not** revoke an already-issued JWT, because the Redis record is a separate store. Before
   (or as part of) the Postgres delete: query the Postgres `sessions` table for every
   `sessions.id` belonging to this `user_id`, and call `SessionStore.delete(session_id)` /
   `SessionAuthenticator.end_session(session_id)` for each — this revokes every device's active
   session immediately, not just the one making the delete request. Do this **before** the
   Postgres cascade removes the `sessions` rows (you need to read them first to know which Redis
   keys to clear).
2. **Celery-held artifacts** (design's own wording in §7.6/§9): CV parsing (P5-04) does not
   persist uploaded bytes anywhere durable — only the structured profile lands in
   `profiles.data` (Postgres, cascades). The Celery result backend (Redis) holds task
   state/progress for `GET /api/jobs/status/{task_id}` but has **no `task_id → user_id`
   index** (a documented, accepted tradeoff — see `backend/app/api/jobs.py` docstring) and
   self-expires via Celery's normal `result_expires` TTL. Document this in `engineer.md` as the
   accepted residual (bounded by the existing TTL, consistent with §6.17/§6.18's
   "retention is a maximum, not a promise" posture) rather than building new `task_id→user`
   tracking infrastructure just for this.
3. **`DELETE /api/me`** (new router, `backend/app/api/me.py`, following the existing
   Router→Service→Repository layering):
   - Requires auth (`require_auth` dependency, same pattern as `profile.py`/`jobs.py`); guests
     get a `403`/`404` (nothing to erase) — pick whichever status code matches the existing
     auth-dependency conventions in the codebase, be consistent.
   - Runs the Redis session-invalidation step, then the Postgres `users` delete, inside one
     logical operation; make it **idempotent** (deleting an already-deleted/unknown user id is
     not a 500).
   - Returns `204 No Content` (or a small confirmation body — check what similar endpoints do)
     on success.
4. **`GET /api/me/export`** (same router):
   - Requires auth; returns a single JSON document (or a downloadable JSON file via
     `StreamingResponse`/`Content-Disposition: attachment` — engineer's call, check how
     `pdp-generator`/other file-returning endpoints in this codebase do it for consistency) with
     every row this user owns: profile, preferences, conversations + messages,
     message_feedback, free-text feedback, their own `kb_documents`/`kb_chunks` (their CV, not
     shared/global ones — filter `user_id = this user`, never leak shared `user_id IS NULL`
     rows), `user_memories`, `pdps`, `goals`/`milestones`/`tasks`/`progress_entries`. Pull via
     the existing repository layer (add read methods where missing) — do not hand-roll raw SQL
     bypassing the repository pattern.
   - `kb_chunks`/`user_memories` carry `vector(4096)` embedding columns — **exclude the raw
     embedding vectors from the export** (they're a derived artifact, not something a user needs
     back, and dumping a 4096-float array per row bloats the export pointlessly); include the
     source text/metadata.
5. **Wire the new endpoints through the BFF.** SEC-04 replaced the blanket Next.js `rewrites()`
   passthrough with a catch-all Route Handler
   (`frontend/app/api/[...path]/route.ts`) that forwards `Authorization` server-side from the
   httpOnly cookie — `DELETE`/`GET /api/me*` should already work through that generic proxy
   with no frontend changes needed. Verify this rather than assuming it (add a test hitting the
   catch-all with these paths if one doesn't already exist for a DELETE method).
6. **Tests**: erasure cascades every store (spin up/use whatever pattern P2's integration tests
   use for a live Postgres check, or verify via repository-level assertions if a live DB isn't
   available in this sandbox — check `make test-integration*` conventions from P2); Redis
   sessions for the deleted user are gone (existing JWT now 401s); export returns a JSON
   document containing the expected sections and excludes other users' data and raw embedding
   vectors; unauthenticated / guest calls are rejected.

## Acceptance criteria
- [ ] `DELETE /api/me` removes the user's Postgres footprint (cascade) and invalidates all of
      that user's live Redis sessions (all devices, not just the caller's).
- [ ] `DELETE /api/me` is idempotent and does not 500 on a user with no data.
- [ ] `GET /api/me/export` returns a complete export of the user's own data (see table list
      above), scoped strictly to `user_id = caller`, excluding raw embedding vectors.
- [ ] Both endpoints require auth; guests are rejected.
- [ ] Both endpoints reachable through the SEC-04 BFF catch-all proxy with no bypass.
- [ ] Tests cover cascade completeness, Redis session revocation, export scoping/exclusions,
      and the auth/guest rejection paths.

## Design references
- dev-board/app-design-and-features.md §7.6 "Right to erasure (Art. 17)... Portability (Art.
  20)", §9 API surface (`DELETE /api/me`, `GET /api/me/export`).
- dev-board/tasks.md — SEC block, item **S6**.
- Existing precedent: `backend/app/api/profile.py` / `backend/app/api/jobs.py` (router
  structure + auth dependency usage), `backend/app/repositories/models/*` (cascade FKs already
  in place), `backend/app/services/auth.py::SessionAuthenticator` (session revocation).

## Constraints / non-goals
- Do not build a periodic retention-purge job here (that's P9's **S14**) — this is the
  on-demand, user-triggered erasure/export only.
- Do not build admin-side audit logging for these calls (admin panel + audit trail is
  deliberately deferred to the P11 pre-go-live phase).
- Do not add new `task_id → user_id` Celery tracking infrastructure — document the accepted
  residual instead (see point 2 above).
