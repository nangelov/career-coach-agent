# Architecture review — P5-05-profile-crud · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 API surface | `GET/PUT /api/profile` — read/update structured profile (API table line 398) | Both handlers added to the existing `app/api/profile.py` router (`/api` prefix); no second router for the same resource | None |
| A2 | §8 layering (Router→Service→Repository) | Router thin; a `ProfileStore` port the service/router depends on; Postgres/ORM confined to the repository adapter | Router depends only on the `ProfileStore` ABC (`app/services/profile_store.py`); SQLAlchemy imported solely in `app/repositories/profile_store.py::PostgresProfileStore`. Port in `services/`, impl in `repositories/` — mirrors `UserStore`/`FeedbackReader` exactly | None |
| A3 | §4 data ownership | `profiles.data` JSONB, one row per user (`unique` on `user_id`), reused across chats (no re-upload) | `upsert` = `INSERT ... ON CONFLICT (user_id) DO UPDATE`; keys on `users.id`; reuses the same row the P5-04 Celery task writes. No parallel table/shape introduced | None |
| A4 | §7 AuthZ (users read only their own profile) | Always the verified token subject; no path/query `user_id`; cross-user denied | Both handlers key on `current_user.user_id` only; no client-supplied id; cross-user isolation test passes. Matches the `profile_ingest.py::submit` posture | None |
| A5 | §4 auth gating / guest posture | `require_auth`; guests have no persisted profile (FK-anchored to `users`) | Both endpoints `Depends(require_auth)`; guest `GET` short-circuits to empty `ProfileSchema` (no DB hit), guest `PUT` → `403`. Mirrors P5-04's documented guest decision | None |
| A6 | §5.1 schema authority | Keep `ProfileSchema` (P5-03) authoritative; add a DTO only if genuinely needed | Reuses `app.ingestion.profile.ProfileSchema` as the wire contract on both directions; no duplicate shape. `services`→`ingestion` coupling already established | None |
| A7 | §4 datastore posture | Postgres via shared `PostgresConnectionProvider`; no ad-hoc engines; Postgres/Redis only | All DB access through `self._provider.session()`; `build_profile_store` fails loudly via `_require_pg_provider` (profile can't degrade to Redis-only — FK reality). No new stores | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — router (`api/`) → port (`services/`) → Postgres adapter (`repositories/`); ORM/SQLAlchemy nowhere but the adapter.
- [x] Honors locked decisions — Postgres (pgvector+JSONB)+Redis only; SSO-only auth via `require_auth` (no passwords touched); no ReAct parser / no Mongo introduced.
- [x] Interfaces-before-implementations — `ProfileStore` ABC seam with `InMemoryProfileStore` test double + `PostgresProfileStore`; consistent with the blessed port-in-services / impl-in-repositories idiom (`UserStore`, `FeedbackReader`).
- [x] Budget posture — free/OSS/self-hosted; no paid dependency added.
- [x] Phase fit — strictly P5 read/write of the already-stored profile; no CV-parse changes (P5-04), no `/api/jobs/status` (P5-06), no frontend (P5-07).

## Notes
- Composition-root wiring (`build_profile_store` + `AppStateKeys.PROFILE_STORE` + lazy `get_profile_store` dependency cached on `app.state`, overridable in tests) matches the codebase-wide pattern; no rogue pool.
- No-profile → empty `200` (rather than `404`) is a defensible, documented API contract choice that keeps `GET`/`PUT` symmetric for the P5-07 view/edit UI and leans on `ProfileSchema`'s graceful-degradation default; it does not couple to later phases. Acceptable.
- Follow-up (non-blocking, informational): because `ProfileSchema` fields all default to empty and pydantic ignores unknown keys, a `PUT` body of `{}` or one containing only unrecognized keys validates to an empty profile and overwrites a populated one. This is by-design for graceful degradation and out of scope here; if P5-07 UX later wants edit-safety, consider a partial/merge semantics decision at that layer — not a design defect now.
- No new design ruling recorded — this task is a clean application of the already-blessed store port/adapter placement (persistent impl in `repositories/`, ABC seam in `services/`).
