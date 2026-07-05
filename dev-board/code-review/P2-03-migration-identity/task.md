# Task P2-03-migration-identity — Migration: identity/docs (JSONB)
- **Phase:** P2   **Status:** ENG   **Tags:** (B)

## Scope
Add the **first real Alembic migration** on top of P2-02's baseline (`0001`), plus the SQLAlchemy ORM
models it derives from (subclassing `Base` from `app/repositories/postgres.py`, per §4/§8). This covers the
**identity/docs** table group only (design §4 "Postgres — identity, conversation & documents"):

- `users` — id (PK, uuid), OIDC `provider` + `sub` (unique together — one identity per provider), `email`,
  `display_name`, `created_at`, `settings JSONB`. **No password columns** (SSO-only, §7.1 — this is a hard
  design constraint, not just an omission).
- `profiles` — one structured CV/profile per user (skills, experience, education, goals) as **JSONB**; FK to
  `users.id`.
- `preferences` — per-user personalization settings (tone, formality, language, do/don't) as **JSONB**;
  FK to `users.id`. (§5.4)
- `sessions` — session id (PK — reuse the same string/uuid shape the app already generates client-side,
  see `frontend`'s `crypto.randomUUID()` from P1-08 and `session_id: str` in `ChatRequest`), `user_id`
  (nullable FK to `users.id` — **null means guest**), `created_at`, `expires_at`. Note: **guests are
  Redis-only for message history** (§4: *"Guests get NO persisted history"*) — this `sessions` row is
  still useful as the identity-linkage anchor for logged-in sessions; do not persist guest message content
  here.
- `conversations` — groups messages under a session/user (id, session_id FK, user_id nullable FK,
  created_at, title/summary optional).
- `messages` — ordered messages: id, conversation_id FK, **`message_id`** (the stable id already minted by
  `ChatService` as `uuid4().hex` — see `app/services/chat.py`; store it as the natural key /
  unique-indexed column other tables like `message_feedback` reference), `role`
  (`user`/`assistant`/`tool`/`system` — match `app/llm/types.py`'s `Role` literal), `content` (text),
  `created_at`, `trace JSONB` (agent-trace metadata — tool calls, timings; nullable, future-proofing for
  P4's multi-agent trace, not populated yet).
- `message_feedback` — `message_id` (FK/reference to `messages.message_id`), `user_id`/`session_id`,
  `rating` (up/down — use a small enum or checked varchar), optional `reason` text, `created_at`. (§5.5 —
  this table is the schema the P9 `POST /api/messages/{message_id}/feedback` endpoint will write to; no
  endpoint work here, schema only.)
- `feedback` — free-text product feedback (replaces v1's JSON files under `data/feedback/`): id, optional
  `user_id`/`session_id`, `contact` (nullable, matches v1's `contact` param), `content` text, `created_at`.

Read `app/llm/types.py` (`Role`, `ChatMessage`) and `app/services/chat.py` (`message_id = uuid4().hex`,
`session_id: str`) first — these existing runtime shapes must be representable by the schema without
forcing a type change on the app side.

## Build
- ORM models in a sensible module layout under `app/repositories/` (e.g. `app/repositories/models/identity.py`
  or flat files — your call, but subclass the shared `Base` from `postgres.py` and document the layout
  choice in `engineer.md` since P2-04/05 will follow the same convention).
- One Alembic migration (`alembic revision --autogenerate -m "identity and docs tables"`, reviewed/edited by
  hand — autogenerate is a starting point, not gospel) with `down_revision` pointing at P2-02's `0001`
  baseline. Verify the generated DDL matches the models (types, nullability, FKs, indexes) — don't just
  accept autogenerate blindly.
- Appropriate indexes/constraints: unique `(provider, sub)` on `users`; unique index on `messages.message_id`;
  FK indexes where Postgres doesn't create them automatically; `ON DELETE CASCADE` where deleting a user
  should cascade-delete their profile/preferences/sessions/conversations/messages/feedback (GDPR-delete
  posture per §4's "simpler GDPR delete" framing) — but do **not** cascade-delete `feedback` rows if you
  decide product feedback should outlive the user account (document your call either way).
- `JSONB` columns via SQLAlchemy's `postgresql.JSONB` type (not generic `JSON`) to match the design's
  explicit "JSONB" language and get Postgres-native indexing options later.

## Verification
- Same posture as P2-02: verify live against the docker-compose Postgres (`alembic upgrade head` then
  `alembic downgrade` back to `0001`, both clean) if a live DB is available in this environment; document
  clearly if it isn't.
- A lightweight integration test (real Postgres via docker-compose, or the SQLite-plumbing style from
  P2-01 if the JSONB/FK features degrade gracefully enough — JSONB does **not** exist in SQLite, so this
  likely needs the real Postgres container; document which you used and why) that inserts one row per new
  table with valid FKs and reads it back, proving the schema is usable, not just that DDL applies.
- `ruff` + `mypy` clean on new/edited Python files (ORM models included).

## Acceptance criteria
- [ ] ORM models for all 7 tables (`users`, `profiles`, `preferences`, `sessions`, `conversations`,
      `messages`, `message_feedback`, `feedback` — 8 tables, the list has 8 not 7, count carefully) exist,
      subclass the shared `Base`, and match the field list above.
- [ ] One Alembic migration builds on the `0001` baseline and applies/reverts cleanly.
- [ ] `users` has no password column; unique `(provider, sub)`.
- [ ] `messages.message_id` uniquely indexed and matches the runtime `uuid4().hex` string shape already
      minted in `app/services/chat.py`.
- [ ] JSONB used (not plain JSON) for the JSONB-designated columns.
- [ ] At least one insert-and-read-back verification per table (live Postgres or documented equivalent).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/app-design-and-features.md §4 (table list quoted above), §5.5 (message_feedback), §7.1 (no
  passwords, SSO-only), §8 (target project structure)
- dev-board/code-review/P2-02-alembic/engineer.md — the Alembic env/baseline this migration builds on
  (async env, `target_metadata = Base.metadata`, Makefile targets `migrate`/`migrate-down`/`revision`)
- backend/app/services/chat.py — `message_id = uuid4().hex`, `session_id: str` — the existing runtime
  identifiers this schema must accommodate
- backend/app/llm/types.py — `Role` literal, `ChatMessage` shape

## Constraints / non-goals
- No `kb_documents`/`kb_chunks`/`user_memories`/`jobs`/`pdps`/dashboard tables here — that's P2-04/05.
- No actual persistence wiring (no `ChatService`/repository code writing to these tables yet) — that's the
  later P2 task "Persist P1 conversations to Postgres for logged-in users." This task is schema-only.
- No auth/session-creation endpoints (P3) — the `sessions`/`users` tables exist as schema now so later
  migrations and P3 auth work don't need a schema rev just to add the identity FKs.
