# Engineer report — P6-07-roles-api · Revision 1

## Summary
Added the v2 market surface API (design §5.6/§9, replaces v1 job-search — *no listings*):
`GET /api/roles/{role}/requirements` (no login; cache-first; cold role → 202 mine handle) and
`GET /api/roles/{role}/gap` (auth-required; delegates to the P6-05 `SkillsGapService`). Thin
router → `RolesService` policy → repositories/Redis cache, with all mining always enqueued as a
Celery job — **no user-facing turn triggers uncached crawling** (§7.5).

## Files changed
New:
- `app/api/roles.py` — thin router; optional-auth + rate-limit on `/requirements`, auth + guest-403 on `/gap`; maps service outcomes to 200/202.
- `app/services/roles.py` — `RolesService` (cache-first requirements read + gap delegation); `RoleProfileCache` port; `CanonicalRoleResolver`/`MineRoleEnqueuer` ports; `RequirementsHit`/`MiningAccepted` outcomes.
- `app/schemas/roles.py` — `RoleRequirement`, `RoleRequirementsResponse`, `RoleMiningAccepted` (202 handle, same shape as `CvUploadResponse`).
- `tests/test_roles_service.py`, `tests/test_roles_api.py`.

Modified:
- `app/agents/market_agent.py` — public `resolve_canonical_role()` wrapping the existing `_resolve_baseline` (reuse the one taxonomy normalizer; no reinvention).
- `app/tasks/market.py` — `enqueue_mine_role()` port (mirrors `enqueue_cv_ingest`; `apply_async` → task_id).
- `app/services/skills_gap.py` — extracted reusable `rank_requirements()` + `_to_skill_gap()` (DRY: the frequency-ranking/JSONB-coercion now shared by `/requirements` and the gap diff).
- `app/repositories/redis.py` — `RedisRoleProfileCache` adapter (StoreRedis seam, mirrors `RedisRateLimiter`).
- `app/security/dependencies.py` — `resolve_optional_user` (optional-auth; returns `None` instead of 401).
- `app/config.py` — `ROLE_PROFILE_STALE_AFTER_SECONDS`, `ROLE_REQUIREMENTS_CACHE_TTL_SECONDS`.
- `app/bootstrap.py` (`build_roles_service`), `app/app_state.py` (`ROLES_SERVICE`), `app/main.py` (register router).

## Key decisions
- **Cache key = cheap normalization of the raw path param, NOT the taxonomy canonical** (§5.7). A Redis hit short-circuits *before* any DB work — canonicalization itself reads Postgres (embedder taxonomy search), so keying on the canonical would make every "hit" re-hit Postgres, defeating "cache hot roles" and the acceptance test (DB not hit twice). Canonicalization runs only on a miss. Documented in `_cache_key`.
- **Canonical resolution is required for correctness, done only on cache miss.** The miner stores `role_profiles.canonical_role` = taxonomy title; to hit that row (and to enqueue mining under a matching `target_role`) the request must resolve the same canonical. Reused `market_agent.resolve_canonical_role` via an injected `CanonicalRoleResolver` port (service carries no embedder/DB itself). Mining stays Celery-only.
- **Staleness → non-blocking background refresh** (§5.6): a stale-but-available profile is still served at 200, and `enqueue_mine` is fired-and-forgotten. Cache TTL bounds refresh re-enqueues to ~once/window. No Celery-beat schedule here (noted as a possible follow-up in `tasks/celery_app.py`).
- **`/requirements` no-login, rate-limited** (§5.6): `resolve_optional_user` accepts a guest/user token when present else anonymous; rate limit reuses `RateLimitAction.MESSAGE` keyed on session (or client IP when anonymous). Only MESSAGE/UPLOAD exist — MESSAGE is the sensible pick (a query ≈ a message); a dedicated market action would need config + `_policy` changes (scope creep).
- **`/gap` auth + guest-403** mirrors `PUT /api/profile`; `profile_missing`/`ok` → 200 (self-describing `status`, never 500), `role_profile_missing` → same cold-start 202 as `/requirements`.
- **Reused, not duplicated:** `SkillsGapService` (gap), `get_role_profile`, `rank_requirements`, `CvUploadResponse`-shape handle, generic `GET /api/jobs/status/{task_id}` (no second status endpoint), `StoreRedis` seam, `RateLimitService`.

## How to verify
- `.venv/bin/python -m pytest tests/test_roles_service.py tests/test_roles_api.py tests/test_skills_gap.py -q`
- Grep no `/api/jobs` bare route: `openapi()['paths']` → only `/api/jobs/status/{task_id}`, plus `/api/roles/{role}/requirements` and `/gap`.

## Tests (final step — mandatory)
- Full suite: `.venv/bin/python -m pytest -q` → **598 passed, 57 skipped** (18 new; skips = live-DB/ML, unchanged). No failures.
- `.venv/bin/ruff check app/ tests/` → All checks passed. `ruff format --check` on all 14 changed/new files → already formatted.
- `.venv/bin/mypy` on the 12 changed app modules → Success, no issues.
- Note: `ruff format --check .` also flags 4 files from sibling P6-02/P6-03/P6-06 (`app/repositories/models/market.py`, `app/tools/tavily_pool.py`, `tests/test_market_models.py`, `tests/test_taxonomy_seed.py`) — pre-existing ruff-version drift on those (uncommitted) tasks' files, **not touched by this task**.

## Self-check
- [x] Meets acceptance criteria: cache-hit ranked+cited 200; cache-miss 202 + pollable task_id; second request served from Redis with DB/resolver hit once (spy-asserted); `/gap` auth + guest-403 + graceful degrade (no 500); both routes registered; mining only via `.apply_async`, never awaited inline; no `GET/POST /api/jobs` route.
- [x] No secrets committed; Router → Service → Repository layering respected (router HTTP-only; service off the driver; DB via `repositories/market`, cache via `repositories/redis`).
- [x] Tests/lints/mypy pass (pasted above).
