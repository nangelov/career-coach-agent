# Architecture review — P6-07-roles-api · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target tree | `api/roles.py` — target roles + market requirement profiles | New `app/api/roles.py` thin router; `services/roles.py` policy; `schemas/roles.py` wire shapes — all in the right modules | none |
| A2 | §8 layering | Router → Service → Repository; router HTTP-only, service off the driver | Router does auth/rate-limit/status-mapping only; `RolesService` depends on ports; DB via `repositories/market.get_role_profile`, cache via `repositories/redis` | none |
| A3 | §5.6/§7.5 no uncached crawling on a turn | Mining always a Celery job, never awaited inline | `get_requirements`/`get_gap` only ever call `enqueue_mine(...)` (`apply_async`); cold role → 202 handle; no synchronous mine path | none |
| A4 | interfaces-before-impl (§8) | Real seams for cache/resolver/enqueuer | `RoleProfileCache` ABC + `CanonicalRoleResolver`/`MineRoleEnqueuer` Protocols in services; `RedisRoleProfileCache` adapter in repositories — mirrors the `RateLimiter`/`RedisRateLimiter` convention | none |
| A5 | §5.6 guest access | Guests can query market requirements, no account | `/requirements` uses new `resolve_optional_user` (None instead of 401), keyed for rate-limit on session-or-IP | none |
| A6 | §5.6 gap needs profile | `/gap` requires a persisted profile (logged-in only) | `require_auth` + explicit guest (`user_id is None`) → 403, mirrors `PUT /api/profile` | none |
| A7 | §5.6 citations + ranking | Every requirement frequency-ranked and cited | Reuses `rank_requirements` (extracted, DRY); `RoleRequirement.evidence` carries citations; `evidence_count`/`refreshed_at` exposed | none |
| A8 | §5.6 periodic refresh | Stale profile refreshed without blocking | Stale-but-available served at 200 + fire-and-forget `enqueue_mine`; `ROLE_PROFILE_STALE_AFTER_SECONDS` config | none (beat sweep noted as follow-up N2) |
| A9 | §5.7 cache hot roles | Redis short-circuits before DB | Cheap raw-param normalization keys Redis; hit returns serialized response with zero Postgres/resolver access; canonicalization only on miss | blessed — see Notes N1 |
| A10 | §9 API surface | `/api/roles/{role}/requirements` + `/gap` replace `/api/jobs`; no listings | Both routes registered in `main.py`; no bare `/api/jobs`; no listing payload — requirement profile only | none |
| A11 | reuse P5-06 status endpoint | One generic job-status endpoint | 202 returns `RoleMiningAccepted` (mirrors `CvUploadResponse` `task_id`+`status`); no second status route built | none |
| A12 | DRY reuse | Reuse taxonomy normalizer, gap service, mine task | `resolve_canonical_role` (single normalizer, wraps `_resolve_baseline`), `SkillsGapService`, `enqueue_mine_role`, `get_role_profile` all reused, not reinvented | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repository) — ports in services, adapter in repositories (established convention)
- [x] Honors locked decisions — Postgres+Redis only (no new store), Celery for async mining, in-process sentence-transformers embedder via composition root, SSO/session-JWT auth reused; no ReAct parser touched
- [x] Interfaces-before-implementations — cache/resolver/enqueuer are real swappable seams; service carries no driver/embedder itself
- [x] Budget posture — no paid services; reuses in-process embedder + self-hosted Redis/Postgres/Celery
- [x] Data ownership (§4/§7) — shared market corpus is user-agnostic (`role_profiles` keyed on canonical role, amortized across users); gap is user-scoped behind auth; guests read shared corpus only

## Notes
- N1 (blessed pattern): cache key is the cheap raw-param normalization, **not** the taxonomy canonical. This is correct — canonicalization itself reads Postgres, so keying on the canonical would make every "hit" re-hit the DB and defeat §5.7. Two spellings → two cheap entries, each resolving to one `role_profiles` row on miss. Good seam design; keep it.
- N2 (follow-up, cheap): no Celery-beat schedule for a periodic stale-sweep — refresh is opportunistic (triggered by a request on a stale profile). Engineer flagged a possible `tasks/celery_app.py` beat entry later. Acceptable for P6; a cold-but-stale role that no one queries never refreshes, which is fine (nothing to serve staleness to).
- N3 (follow-up, cheap-to-tighten): market queries are rate-limited on `RateLimitAction.MESSAGE`, sharing the guest 10-message chat budget (§6.8). A guest browsing requirements burns chat budget. §5.6 doesn't define a separate market-query budget, so this is under-specified rather than wrong; adding a dedicated `RateLimitAction.MARKET_QUERY` is a one-line-of-config change if product wants to decouple them. Not blocking — logged so it isn't silently re-litigated.
