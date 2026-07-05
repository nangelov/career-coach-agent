# Architecture review — P2-03-migration-identity · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §4 table set | 8 identity/conversation/doc tables: `users`, `profiles`, `preferences`, `sessions`, `conversations`, `messages`, `message_feedback`, `feedback` | All 8 ORM models present in `models/identity.py` and created in migration `0002`; no P2-04/05 tables leaked in | none |
| A2 | §7.1 SSO-only | `users` has `provider`+`sub`, **no password/credential column** | `User` has `provider`,`sub`,`email`,`display_name`,`settings`; zero credential columns; unique `(provider, sub)` = `uq_users_provider_sub` | none — hard constraint honored |
| A3 | §4 JSONB (not JSON) | `settings`, profile/preference docs, `trace` as JSONB | `postgresql.JSONB` on `users.settings`, `profiles.data`, `preferences.data`, `messages.trace` (never generic `JSON`) | none |
| A4 | §5.5 stable message_id | `messages.message_id` = the app's `uuid4().hex`, unique, referenced by `message_feedback` | `message_id String(32)` unique, `default=uuid4().hex`; `MessageFeedback.message_id` FKs to `messages.message_id` (natural key, not surrogate PK) | none — matches `ChatService` runtime shape exactly |
| A5 | §5.5 rating | per-message up/down + optional reason | `rating` String(8) + `ck_message_feedback_rating IN ('up','down')`; nullable `reason` | none |
| A6 | Role vocabulary | `role` matches `app.llm.types.Role` literal (`system/user/assistant/tool`) | `ck_messages_role` constrains to exactly those 4 values; `_ROLE_VALUES` documented as kept in lockstep | none — schema representable by runtime type without change |
| A7 | §4 guests Redis-only | `sessions.user_id` nullable (null = guest); no forced guest history persistence | `Session.user_id` nullable FK; string PK reuses client `crypto.randomUUID()` shape (`session_id: str`); schema does not force guest message content into these tables | none |
| A8 | §4 GDPR-delete posture | user-delete cascades to owned rows; product feedback may outlive account | CASCADE on profile/preferences/sessions/conversations/messages/message_feedback; `feedback` FKs `ON DELETE SET NULL` (documented deliberate exception the task allowed) | none |
| A9 | §5.4 personalization stores | `preferences` = authoritative explicit prefs (JSONB), one per user; distinct from inferred `user_memories` (deferred) | `Preference.data` JSONB, `user_id` unique; `user_memories` correctly left to P2-04 | none |
| A10 | §8 target structure | models in the repository layer, subclassing shared `Base` | `repositories/models/` subpackage, all 8 subclass `Base` from `postgres.py`; §8 shows flat `postgres.py`/`redis.py` but a `models/` subpackage stays within the repository layer | none — accepted extension (see Notes N1) |
| A11 | P2-02 migration chain | one migration with `down_revision="0001"`, applies/reverts cleanly | `0002` revises `0001`; live upgrade→downgrade→upgrade verified clean; autogenerate reports no drift | none |
| A12 | Phase fit | schema-only, no premature coupling to later phases | `trace JSONB` nullable + unpopulated (P4 future-proofing); no persistence wiring, no auth/session endpoints (P3); no kb/memory/dashboard tables | none — foundation-first sequencing respected |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — models in repository layer; no service/router touched
- [x] Honors locked decisions — Postgres + JSONB only (no Mongo); SSO-only, no passwords; no pgvector/LangGraph/LangMem prematurely introduced (correctly deferred to P2-04)
- [x] Interfaces-before-implementations — N/A for a schema task; models sit behind the existing `repositories/` seam
- [x] Budget posture respected — self-hosted Postgres, no managed tier, no paid services introduced

## Notes
- **N1 (blessed pattern, follow-up for P2-04/05):** the `repositories/models/<group>.py` subpackage extends §8's flat
  `repositories/postgres.py` layout. Acceptable and sensible — it keeps `Base.metadata` populated via a single import
  for `env.py`/tests and scales per table group. P2-04/05 should follow the same convention (new module + import line in
  `models/__init__.py`), not re-litigate it. Logging this as the accepted repository-models layout.
- **N2 (minor, non-blocking):** `messages` orders by `created_at` only (no explicit sequence column). Sub-second
  `created_at` collisions within a conversation are theoretically possible under concurrent writes; ordering by
  `(created_at, id)` is a safe tie-break the persistence task (later P2) can adopt. Schema is fine as-is; no rev needed.
- **N3:** `role`/`rating` as `CheckConstraint` over `String` rather than native PG `ENUM` is the right call for keeping
  the role set in lockstep with `app.llm.types.Role` (a cheap check-constraint swap vs. a fragile `ALTER TYPE`).
- Verification (live docker-compose Postgres upgrade/downgrade/no-drift + per-table insert-and-read-back) is the
  correctness-reviewer's gate; from a design standpoint the schema is representable by the existing runtime shapes
  (`session_id: str`, `message_id = uuid4().hex`, `Role`) without forcing any app-side type change.
