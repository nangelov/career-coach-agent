# Code review — P2-03-migration-identity · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/repositories/models/identity.py:216-254 | `messages` are "ordered" (§4) but the only orderable column is `created_at` (timestamptz with `server_default now()`); the surrogate PK is a random UUID (not monotonic). Two messages in the same turn/transaction can share a `created_at`, making read-back order ambiguous. Schema-only task, so not blocking. | When persistence is wired (later P2 task), add an explicit ordinal/sequence column or rely on `created_at` + a deterministic tiebreak. No change needed now — flag for the persistence task. |
| C2 | nit | backend/app/repositories/models/identity.py:257-295 | `message_feedback` has no unique constraint on `(message_id, user_id)` / `(message_id, session_id)`, so one user could persist multiple 👍/👎 rows for the same message. §5.5 is a single per-message reaction; P9 will need to upsert or dedupe. | Optional: add a partial/unique constraint in the P9 feedback-endpoint task, or have the endpoint upsert. Acceptable to defer. |

## Notes
Verified live against the docker-compose Postgres (pgvector/pg16 on :5432, DSN from `.env`):
- `alembic upgrade head` → `alembic current` = `0002 (head)`.
- `alembic revision --autogenerate` drift check → empty `upgrade()`/`downgrade()` (`pass`) → **no drift** between models and migration (tmp file deleted).
- `alembic downgrade 0001` → all 8 identity tables gone (queried `information_schema` = `[]`); `upgrade head` reapplied cleanly.
- `pytest tests/test_identity_models.py` → **6 passed** (real inserts/read-back per table, `(provider,sub)` + `message_id` uniqueness raise, `role` check-constraint rejects out-of-vocab, user-delete cascade, product-`feedback` SET NULL survival).
- `ruff check` / `ruff format --check` clean; `mypy app/ migrations/` clean; full suite **89 passed**.

Correctness / security checks that pass:
- **No password/credential column** anywhere on `users` (§7.1 hard constraint); unique `(provider, sub)` present.
- **`messages.message_id`** is `String(32)` unique — matches `ChatService`'s `uuid4().hex` (verified in `app/services/chat.py:187`); `message_feedback.message_id` FKs to it (the natural key, backed by the unique constraint FK requires), not the surrogate PK.
- **`role`** check-constraint values `('system','user','assistant','tool')` are in lockstep with `app.llm.types.Role` (verified).
- **JSONB (not JSON)** via `postgresql.JSONB` for `users.settings` / `profiles.data` / `preferences.data` / `messages.trace`.
- **GDPR cascade posture** correct: user-delete cascades to profile/preferences/sessions/conversations/messages/message_feedback; product `feedback` is `ON DELETE SET NULL` (deliberate, task-allowed, tested).
- **`sessions.id`** is `String(64)` client-minted PK, `user_id` nullable = guest — accommodates the existing `session_id: str` runtime shape without an app-side type change.
- DSN single-source respected (`env.py` injects `settings.DATABASE_URL`, `alembic.ini` has no `sqlalchemy.url`); no `CREATE EXTENSION` in the migration (pgvector stays in the P0-07 init script); no migration auto-run in `app/` lifespan (`grep` empty).
- Integration test is CI-safe: skips when no Postgres reachable, wraps expected-failure flushes in `begin_nested()` savepoints, and rolls back the outer transaction (DB left as found). The P2-01 `Base.metadata == {}` assertion was correctly updated to reflect models now populating the shared metadata.

C1/C2 are nits on a schema-only task where persistence wiring and the P9 endpoint are explicit later tasks; neither gates this migration.
