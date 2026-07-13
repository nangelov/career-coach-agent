# Architecture review — P6-02-market-schema · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | market-intel models under `repositories/models/`, colocated table group | `market.py` holds `RoleProfile` + `JobPosting`; `jobs.py` deleted; both re-exported via `models/__init__.py` `__all__` mirroring the existing group convention | none |
| A2 | §5.6 `role_profiles` shape | id UUID PK, `canonical_role` unique, `taxonomy_id` nullable, `requirements`/`sources` JSONB, `evidence_count`, `refreshed_at`, timestamps | all present; `requirements` default `{}`, `sources` default `[]`, `evidence_count` default 0, `refreshed_at` nullable | none |
| A3 | §5.6 global / non-personal | no `user_id`, no FK, no cascade — never touched by GDPR delete (§7.6) | neither table carries `user_id`; no FK/cascade; asserted by `test_tables_are_global_no_user_id` | none |
| A4 | §5.6 drop per-posting match scoring | `match_score` removed; match = user△role_profile computed, not stored; no `/api/jobs` | column dropped in migration + ORM; no endpoint added (schema-only) | none |
| A5 | §5.6 `job_postings` raw evidence | rename `jobs`→`job_postings`; TTL cache; dedup preserved; `target_role`+`expires_at` NOT NULL, indexed | rename + dependent constraint/index/pk renamed; dedup `(source,external_id)` preserved; both new cols NOT NULL via transient server_default then dropped to match ORM | none |
| A6 | §7.6 third-party PII | schema supports ingest-time stripping (no recruiter columns); enforcement deferred to P6-04 | no recruiter name/email/phone columns; `raw` JSONB kept for re-parse; docstrings cite §7.6 and defer enforcement to P6-04 | none |
| A7 | §4 data ownership | shared corpus, user-scoped rows unaffected | global tables added; no change to user-scoped stores; Postgres/JSONB only, no new store | none |
| A8 | migration chain | next sequential rev after `0006`, up/down reversible | rev `0007` down_revision `0006`; `downgrade()` fully reverses (rename back, re-add `match_score`, drop `role_profiles`); `alembic check` clean per report | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — repository/model layer only, no cross-layer leak; router/service untouched.
- [x] Honors locked decisions — Postgres (pgvector + JSONB) only, no new store; no ReAct/SSO/embedding surface touched; product-scope LOCKED (evidence-only, not a job board) respected.
- [x] Interfaces-before-implementations — N/A (schema task); no premature ingestion coupling (embedding write path correctly deferred to P6-04).
- [x] Budget posture respected — no new paid deps.

## Notes
- Rename fan-out verified clean: no remaining `app.repositories.models.jobs.Job` imports. Residual "job" tokens are unrelated (`services/jobs.py` = Celery job-status; `agents/graph.py` "Job Search" node names; `internet_search.py` docstring) and out of scope.
- The `20260705_0004` migration docstring still references the old `app.repositories.models.jobs` module — correctly left untouched (migration history is immutable, not a live import).
- `RoleProfile` having *no* `user_id` column (vs `user_id IS NULL`) is stronger than the §4 kb_documents pattern and is exactly what §5.6 prescribes for a standalone global artifact — accepted.
- Phase fit: P6 schema-only; no ingestion/mining, no `/api/jobs`, no `role_profiles` embedding write path — foundation-first sequencing honored.
