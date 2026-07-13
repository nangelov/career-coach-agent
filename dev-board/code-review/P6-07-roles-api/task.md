# Task P6-07-roles-api — GET /api/roles/{role}/requirements + /gap
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullet 9: `GET /api/roles/{role}/requirements` + `GET /api/roles/{role}/gap`; Redis cache for hot
roles; periodic refresh of stale profiles. **No user-facing turn triggers uncached crawling** — mining is
always a Celery job (§7.5).

Add `app/api/roles.py` (design §8 target tree: `api/roles.py — target roles + market requirement profiles`),
following the existing thin-router convention (`api/profile.py`/`api/jobs.py` — Router → Service → Repository,
authN/rate-limit + shaping only, business logic in an injected service).

**`GET /api/roles/{role}/requirements`** (design §9: *"replaces `/api/jobs`; no listings"*):
- **No auth required** — design §5.6: *"Guests: can query market requirements (shared corpus, no account
  needed)"*. Still subject to the existing per-session/IP rate limiting (reuse `RateLimitService`, pick a
  sensible `RateLimitAction`).
- Normalize `role` (path param) to a canonical role string the same way `market_agent.py`'s baseline
  resolution does (reuse its normalization, don't reinvent it) and look up the cached
  `app.repositories.market.get_role_profile`.
- **Cache hit** (a `RoleProfile` exists): return `200` with the frequency-ranked `requirements` (skill →
  frequency/weight/evidence — cited, per design §5.6 "every requirement carries citations"), `evidence_count`,
  `refreshed_at`. Cache the **serialized response** in Redis keyed on the normalized role (TTL — "cache hot
  roles", §5.6/§5.7) so a second request for the same role does not re-hit Postgres, let alone re-mine — follow
  the existing `StoreRedis`-protocol + injectable-port convention (`app/repositories/redis.py`, mirrors
  `RedisRateLimiter`/`RedisSessionStore`).
- **Staleness → background refresh, not a blocking re-mine**: if the cached `RoleProfile.refreshed_at` is
  older than a configurable staleness window (new `Settings` field, e.g.
  `ROLE_PROFILE_STALE_AFTER_SECONDS`), still return the cached (stale-but-available) data at `200`, but
  **enqueue** `app.tasks.market.mine_role_task.delay(target_role=<canonical>)` in the background (fire-and-
  forget — do not await its result) so the *next* request gets fresher data. This satisfies "periodic refresh
  of stale profiles" without a live-DB-gated Celery-beat schedule (out of scope here — note it as a documented
  follow-up if you think a beat entry belongs in `tasks/celery_app.py` later).
- **Cache miss** (no `RoleProfile` row at all — role never mined): enqueue `mine_role_task.delay(...)` and
  return **`202`** with a job handle in the **same shape** P5-04's `CvUploadResponse` established (`task_id` +
  `status: "accepted"`) so the client polls the **existing** `GET /api/jobs/status/{task_id}` (P5-06,
  deliberately generic to any Celery producer — do not build a second status endpoint).

**`GET /api/roles/{role}/gap`** (design §9: *"skills gap: user profile △ role profile"*):
- **Requires auth** (`require_auth`) — a skills gap needs a persisted `Profile`, which only exists for
  logged-in users (mirrors `PUT /api/profile`'s guest-rejection posture, P5-05). A guest gets `403`.
- Delegates to the P6-05 `SkillsGapService` (already built — reuse it, do not recompute inline). Map its
  `status` field to the HTTP contract: `"ok"` → `200` with `SkillsGapResult`; `"profile_missing"` → `200` (or
  `409`, your call — document it) with a clear "upload a CV first" signal, no 500; `"role_profile_missing"` →
  the **same** cache-miss behavior as `/requirements` (enqueue mining, return `202` + job handle) so a client
  hitting `/gap` cold still makes forward progress without a second round-trip through `/requirements` first.

## Acceptance criteria
- [ ] `GET /api/roles/{role}/requirements`: no-auth cache-hit returns ranked+cited requirements; cache-miss
      returns `202` + pollable `task_id`; a second request for the same role after a mine completes is served
      from Redis (unit test asserts the repository/DB is not hit twice — inject a spy/fake).
- [ ] `GET /api/roles/{role}/gap`: requires auth; delegates to `SkillsGapService`; degrades per the mapping
      above without ever 500-ing on a missing profile/role_profile.
- [ ] Both routes wired into the FastAPI app (check `app/main.py` / router-registration convention used by the
      other `api/*.py` modules) and covered by request-level tests (FastAPI `TestClient`/`httpx.AsyncClient`)
      using fake services — no live DB/Celery/Redis in unit tests.
- [ ] `mine_role_task.delay(...)` (or equivalent `.apply_async`) is only ever called from this router/service,
      never awaited inline — confirm no synchronous mining happens on the request path.
- [ ] No `GET/POST /api/jobs` route exists (tasks.md P6 header: dropped).

## Design references
- dev-board/plan.md: Phase 6, bullet 9  ·  dev-board/app-design-and-features.md §5.6, §9 (API surface table
  rows for `/api/roles/{role}/requirements` and `/gap`)
- Reuse: `app/repositories/market.py` (`get_role_profile`), `app/services/skills_gap.py` (`SkillsGapService`,
  P6-05, DONE), `app/tasks/market.py` (`mine_role_task`, P6-04, DONE), `app/schemas/profile.py`
  (`CvUploadResponse` shape as the job-handle precedent), `app/api/jobs.py` / `app/services/jobs.py` (the
  generic task-status endpoint, do not duplicate), `app/repositories/redis.py` (`StoreRedis` protocol +
  Redis-backed adapter convention), `app/services/rate_limiting.py`

## Constraints / non-goals
- No frontend work here (P6-08, next).
- No new migration — this task only reads `role_profiles` and calls the existing Celery task.
- Do not build a second job-status endpoint — reuse `GET /api/jobs/status/{task_id}`.
