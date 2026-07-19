# Architecture review — P9-08-retention-purge · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | read query in `repositories/`, job in `tasks/`, setting in `config.py` | `repositories/retention.py`, `tasks/retention_purge.py`, `config.RETENTION_PURGE_AFTER_DAYS` | none |
| A2 | Single erasure path (SEC-05, §7.6, Art. 17) | reuse `delete_user` cascade, no second delete path | purge feeds each stale id into `PostgresAccountRepository.delete_user`; one cascade in codebase | none — exactly the required posture |
| A3 | Retention window (§6.18 "SSO users: 1 month") | configurable, default 30, not hard-coded | `RETENTION_PURGE_AFTER_DAYS` Field default 30, read in task body | none |
| A4 | Layering (Router→Service→Repo; repos over shared provider, no ad-hoc drivers) | read-only repo over `PostgresConnectionProvider`; task composes own worker-local collaborators | grouped aggregate via shared provider; `_purge_entrypoint` builds+disposes its own provider (worker has no `app.state`) — mirrors `profile_ingest` | none |
| A5 | Interfaces-before-impl | seam ports for finder + eraser | `RetentionRepository` ABC + `StaleUserFinder`/`UserEraser` Protocols; fakeable core | none |
| A6 | "Last activity" definition (task crux) | derive from real usage, no denormalized column/migration | `COALESCE(MAX(messages.created_at), users.created_at)`, LEFT JOINs + HAVING; `sessions.expires_at` deliberately excluded (lazy PG table, future ts) | none — reasoning documented and correct |
| A7 | Guest scope (§4, P3-01/P9-07) | guests Redis-only, no purge job | query joins `users` (SSO-only rows); guests untouched, TTL-expiring | none |
| A8 | Celery periodic (§5.3) | daily beat entry + compose `beat` service | first `beat_schedule` (`crontab(hour=3,minute=0)`); new `beat` compose service mirroring `worker` | none |
| A9 | Budget posture (§11) | free/OSS/self-hosted | Celery beat + Postgres/Redis only, no paid tier | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Repo)
- [x] Honors locked decisions (Postgres+Redis only; no new store; guest Redis-only)
- [x] Interfaces-before-implementations (RetentionRepository ABC + task Protocol ports)
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **No admin carve-out** is the correct reading: `is_admin` is a plain flag on the same `users`
  row and §6.18/§6-26 name no retention exception. Uniform purge is design-conformant.
- **Traces (P11):** correctly out of scope — docstring TODO defers OTel retention to P11's own
  backend config. No premature coupling to unbuilt P11.
- **P12 note** (single-container must run `celery beat` alongside worker) is a legitimate,
  correctly-deferred follow-up — not owed here.
- Task-crux "last activity" definition is well-argued (the `sessions.expires_at` exclusion is a
  design-quality call, not an oversight). No migration added, matching the task's explicit steer
  against a denormalized `last_activity_at` column.
