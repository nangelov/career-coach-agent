# Engineer report — P9-01-message-feedback · Revision 1

## Summary
Implemented per-message 👍/👎 feedback **capture**: `POST /api/messages/{message_id}/feedback`
accepting a thumbs rating + optional free-text reason, persisted to the existing (P2-03)
`message_feedback` table with ownership validation and idempotent upsert. Added a reusable
persistence port (`MessageFeedbackStore`) whose read methods (`get_for_message`,
`list_recent_downvotes`) are ready for the P9-03 LangMem learn step. No LangMem wiring, no
demotion logic, no frontend — capture only, per scope.

The ORM model + base table already existed (P2-03). This task adds the endpoint, service port,
Postgres adapter, wiring, a uniqueness constraint (new migration `0009`), and tests.

## Files changed
- `app/schemas/message_feedback.py` (new) — `MessageFeedbackRequest` (rating `up`/`down` +
  optional reason, capped 2000) and `MessageFeedbackResponse`.
- `app/services/message_feedback.py` (new) — `MessageFeedbackStore` ABC (port) + `MessageOwner`
  + `InMemoryMessageFeedbackStore` test double. Ownership is part of the port contract.
- `app/repositories/message_feedback_store.py` (new) — `PostgresMessageFeedbackStore`: ownership
  join (`messages`→`conversations`), `ON CONFLICT (message_id)` upsert, downvote listing.
- `app/api/message_feedback.py` (new) — thin router; `require_auth`; uniform 404 for
  missing/not-owned (no ownership leak).
- `app/repositories/models/identity.py` — `MessageFeedback`: added
  `UniqueConstraint("message_id")`, dropped the now-redundant single-column index.
- `migrations/versions/20260718_0009_message_feedback_unique.py` (new) — replaces
  `ix_message_feedback_message_id` with `uq_message_feedback_message_id`.
- `app/app_state.py`, `app/bootstrap.py`, `app/main.py` — `MESSAGE_FEEDBACK_STORE` key,
  `build_message_feedback_store`, router registration.
- `tests/test_message_feedback_api.py`, `tests/test_message_feedback_store_postgres.py` (new).

## Key decisions
- **Port lives in `services/`, Postgres impl in `repositories/`** (Router → port → adapter),
  mirroring `ProfileStore`/`FeedbackReader`. Router imports only the port. (§8 layering.)
- **Ownership is enforced in the store, not the router.** `record()` takes the caller identity
  and returns `None` when the message is unknown *or* not the caller's; the router maps that
  single `None` to a uniform **404** (never 403-vs-404), matching `dashboard.py`'s no-leak rule.
  Logged-in users are matched by `user_id` (so feedback on a message from an earlier session
  still resolves); guests by `session_id`. (§7 AuthZ.)
- **One feedback row per message** (a message has exactly one owner) → `UNIQUE(message_id)` and
  `ON CONFLICT (message_id) DO UPDATE`. Resubmitting flips the same row and restamps
  `created_at` (keeps "recent down-votes" meaningful for P9-03). New migration `0009` since the
  base table shipped in `0002`.
- **Persist the message's owning `session_id`/`user_id`, not the caller's** — the caller's
  current session may be fresh/Redis-only and unpersisted, which would violate the
  `message_feedback_session_id` FK. The owner ids equal the caller after the check, so nothing
  leaks. (Caught by the different-session integration test.)
- **Guests allowed through `require_auth`, no message rate-limit added.** Feedback is not a chat
  message/upload, so consuming the guest 10-message budget would be wrong; matches the
  unrate-limited dashboard CRUD. No new unauthenticated surface (§7).

## How to verify
```
cd backend
make lint typecheck                      # ruff + mypy --strict
docker compose -f ../docker-compose.yml -f ../docker-compose.dev-ports.yml up -d --wait db
make migrate-integration                 # applies 0009
make test-integration                    # full suite incl. live-DB integration
```
Manual: `POST /api/messages/{id}/feedback` with `{"rating":"down","reason":"..."}` and a bearer
token → 200 with the stored feedback; resubmit → same row updated; unknown/foreign id → 404.

## Tests (final step — mandatory)
- `ruff check app/ tests/ migrations/` → All checks passed. `ruff format --check` → clean.
- `mypy app/ migrations/` (strict) → Success, no issues (144 files).
- `alembic upgrade head` → applied `0008 -> 0009`. `alembic check` → **No new upgrade operations
  detected** (model/migration consistent, no drift).
- Full suite against live Postgres (`make test-integration`): **819 passed, 1 skipped** (the
  skip is a pre-existing unrelated test; both new message-feedback suites executed — 11 passed).
- One failure found during the run and fixed at root cause: the FK violation from storing the
  caller's (unpersisted) `session_id`; fixed by persisting the message's owning conversation ids
  (see key decisions). Re-ran → green.

## Self-check
- [x] Meets acceptance criteria (endpoint, model/table + `0009` migration, upsert idempotency,
      repository read methods for P9-03, auth reuse incl. guests, tests for up/down/idempotent/
      404-missing/404-not-owned/guest/401/422).
- [x] No secrets committed; Router → Service(port) → Repository layering respected.
- [x] Tests/lints pass (results pasted above).
