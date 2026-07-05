# Engineer report — P2-07-persist-conversations · Revision 2

## Summary
Wired the P1 chat pipeline to **durably persist logged-in users' conversations to Postgres**
while leaving the guest path byte-for-byte unchanged (§4: *"Guests get NO persisted history"*).
Followed the established ports-and-adapters shape: a new `ConversationStore` ABC in the service
layer, a `PostgresConversationStore` adapter in the repository layer (over the P2-01 shared pool
and the P2-03 identity models), injected into `ChatService`. Added an **interim, documented**
`user_id` field to `ChatRequest` as the stand-in for the P3 JWT-derived identity — `None` → guest
(Redis-only), set → logged-in (also persisted). On a restart / Redis eviction, a logged-in turn
now **rehydrates its context from Postgres** when Redis working memory is empty, which is what
makes account chat history survive a restart. Persistence and rehydration are both **best-effort**:
a DB failure is logged and never breaks the user-visible SSE stream.

Verified on the host venv + the live docker-compose Postgres (migration 0002 applied): `ruff`
clean, `mypy --strict` clean (`app/` and the new tests), **135 passed** (12 new; the 4
live-Postgres integration tests actually ran, not skipped).

## Files changed
- `backend/app/services/conversation_store.py` — **new.** The `ConversationStore` **port** (ABC):
  `persist_turn(...) -> conversation_id` and `load_history(...) -> list[ChatMessage]`. Interim
  `user_id` contract documented on the class.
- `backend/app/repositories/conversation_store.py` — **new.** `PostgresConversationStore` adapter
  over `PostgresConnectionProvider` (P2-01) and the `Session`/`Conversation`/`Message` models
  (P2-03). Get-or-creates the session + conversation rows; persists user + assistant messages;
  reads them back ordered for rehydration.
- `backend/app/repositories/__init__.py` — export `PostgresConversationStore`.
- `backend/app/services/chat.py` — `ChatService` gains an optional `conversations` dependency and a
  `user_id` param on `stream_turn`. New `_load_prior` (Redis → Postgres fallback) and `_persist_turn`
  (best-effort) helpers; persist calls added on the `done` and both `cancelled` paths.
- `backend/app/schemas/chat.py` — `ChatRequest` gains the optional, documented interim `user_id` field.
- `backend/app/api/chat.py` — `build_chat_service` constructs the store from `app.state.pg_provider`;
  the `/api/chat` route threads `payload.user_id` into `stream_turn`.
- `backend/tests/test_chat_api.py` — updated the fake service's `stream_turn` signature for the new kwarg.
- `backend/tests/test_chat_persistence.py` — **new.** 9 service-level tests (fakes, no DB):
  logged-in persists, guest persists nothing, cancel persists partial, restart rehydration,
  guest never rehydrates, persist/load failures don't break the stream.
- `backend/tests/test_conversation_store.py` — **new.** 4 live-Postgres integration tests for the
  adapter (write conversation+messages, one-conversation-per-session + ordered `load_history`,
  user-only turn, empty-history).

## Key decisions
- **`user_id` as an optional `ChatRequest` field (not a header).** The task offered either; a body
  field keeps the whole turn contract in one Pydantic model the Next.js client already consumes
  (schemas/chat.py precedent) and is trivially settable by tests / the future P3 dependency. Documented
  as an interim, non-authorization stand-in (P3 populates it from the verified session JWT). Guest
  (`None`) path is unchanged from P1.
- **Adapter in its own `repositories/conversation_store.py`** (not swelling `postgres.py`, which is the
  engine/pool foundation) — parallels how the Redis session-memory adapter sits beside the provider.
- **One conversation per session at this phase.** `persist_turn(conversation_id=None)` get-or-creates
  the session's single conversation, so `ChatService` does not need to thread a conversation id across
  turns (it always passes `None`). Matches the task's "creating one on first turn of a session if not
  supplied" wording.
- **Only user + final/partial-assistant messages are persisted** — the internal tool round-trip
  scaffolding is deliberately not stored, keeping durable history a clean user↔assistant transcript.
  The Redis working memory still carries tool messages within a live session; after a restart the
  rehydrated context is the thinner (but coherent) transcript.
- **Ordering without a sequence column.** All messages of one turn are written with a single
  per-turn `created_at`; `load_history` orders by `(created_at, role_rank[user<assistant])`. Turns are
  separated by wall-clock `created_at` (each turn is its own committed transaction); the role tiebreaker
  disambiguates the user/assistant pair that shares a turn's timestamp — no schema change needed.
- **Persist happens *after* the terminal `done`/`cancelled` event is yielded** (task-sanctioned
  ordering) so the DB write never delays the user-visible stream. Both persist and the Postgres
  rehydration fallback are wrapped best-effort (logged, swallowed) — **a persistence failure must never
  break the SSE stream** (the stream has already delivered its terminal event by then).
- **`persist_turn` assumes the `users` row exists** (P3 creates it at login); it get-or-creates the
  `sessions`/`conversations` rows. A missing user → FK error → caught best-effort. Documented on the adapter.
- **No in-memory production `ConversationStore`.** `ChatService` treats an absent store (`None`) as
  "persistence off" — the guest path and any deployment without a Postgres provider simply skip durable
  writes. Tests inject a fake.

## How to verify
On the host venv, with the live docker-compose Postgres (db publishes 5432; migration 0002 applied):
```bash
set -a && . ./.env && set +a
export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"
cd backend
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format --check app/ tests/
.venv/bin/mypy app/
.venv/bin/mypy tests/test_chat_persistence.py tests/test_conversation_store.py
.venv/bin/python -m pytest -q
```
Results actually observed here:
- `ruff check` → **All checks passed!**; `ruff format --check` → 60 files already formatted.
- `mypy app/` → **Success: no issues found in 41 source files**; `mypy` on the two new tests → Success.
- `pytest -q` → **135 passed** (was 123 before; +12 new). The two integration files (`test_conversation_store.py`,
  4 tests) ran against real Postgres — **0 skipped** — proving conversation+message rows land with the
  right `message_id`/`role`/`content`, one-conversation-per-session, and ordered rehydration.

## Self-check
- [x] Meets acceptance criteria — interim optional `user_id` (guest byte-for-byte unchanged);
  `ConversationStore` port + `PostgresConversationStore` adapter; logged-in turns (incl.
  cancelled/partial) persist to `conversations`/`messages` via the P2-03 schema; guest turns persist
  nothing (explicit test); restart-simulation test proves rehydration from Postgres; persistence
  failures logged + never break the stream (documented + tested); ruff + mypy clean; full suite green.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (port in `services/`, DB access
  confined to `repositories/`; the router only threads a request field into the service).
- [x] Interfaces-before-implementations: `ConversationStore` ABC precedes the Postgres adapter; Postgres+
  Redis only; no ReAct/SSO scope crept in.
- [x] Tests/lints pass (pasted above): 135 passed, ruff clean, mypy clean (app + new tests).

## Response to review (revision 2)

Addressed all five findings from `code-review.md` (verdict CHANGES_REQUESTED, one gating
major). Architecture review was APPROVED — its notes N1/N2/N3 overlap C2/C4/N-ordering and are
covered below where trivial; N2's sequence-column suggestion stays a P4 follow-up as noted.

Re-ran from `backend/` against the live docker-compose Postgres
(`DATABASE_URL=postgresql+asyncpg://…@localhost:5432/…`, migration 0002 applied):
- `ruff check app/ tests/` → **All checks passed!**
- `ruff format --check app/ tests/` → **60 files already formatted**
- `mypy app/` → **Success: no issues found in 41 source files** (and `mypy` on the two new
  test files → Success: 2 source files)
- `pytest -q` → **136 passed** (was 135; +1 new two-turn restart regression test).
- `pytest tests/test_conversation_store.py -v` → the **4 live-Postgres integration tests ran
  and PASSED (not skipped)** — confirmed against real Postgres, printed individually.

- **C1 (major, gating) → fixed.** `_load_prior` (`app/services/chat.py`) now seeds the (empty)
  Redis working memory with the history it rehydrates from Postgres
  (`await self._memory.append(session_id, loaded)`) before returning it. This makes the
  *second and later* post-restart turns find the full context already in Redis instead of
  re-skipping the rehydration branch and silently truncating to the single new turn.
  Added `test_restart_preserves_context_across_multiple_turns` in `test_chat_persistence.py`:
  it persists turn 1 pre-restart, simulates a restart (one fresh `SessionMemory` driving two
  post-restart turns), and asserts turn 3's model call still contains turn 1's `Q1`/`A1` pair.
  Verified this test **fails without the seeding fix** (turn 3 context collapses to
  `[system, Q2, A2, Q3]`, dropping `Q1`/`A1`) and **passes with it** — a genuine C1 guard.
- **C2 (minor) → fixed.** `ChatRequest.session_id` (`app/schemas/chat.py`) is now
  `Field(..., min_length=1, max_length=64)`, matching the `sessions.id` /
  `conversations.session_id` `String(64)` columns, so a logged-in turn can no longer carry a
  session_id that the (best-effort, silently-swallowed) Postgres insert would reject. Added a
  docstring paragraph documenting the alignment and why.
- **C3 (minor) → documented (constraint deferred, by judgment).** Added a docstring block to
  `_resolve_conversation` (`app/repositories/conversation_store.py`) making the
  "one in-flight stream per session" assumption explicit (the SSE turn + Redis cancel flag are
  per-session and the client only fires the next turn after the current stream ends, so
  first-turns serialize in practice), and stating the remedy if a future phase allows
  concurrent per-session turns (unique constraint on `conversations.session_id` or an
  `ON CONFLICT` upsert). I did **not** add the constraint now: it needs a migration for an
  invariant that is phase-scoped and will likely be revisited when conversation-history UI
  lands (multi-conversation-per-session), so documenting the assumption is the lower-risk,
  in-scope choice — consistent with the reviewer leaving this to engineer's judgment.
- **C4 (nit) → fixed.** `load_history` (`app/repositories/conversation_store.py`) now bounds
  the query with `.order_by(created_at.desc(), role_rank.desc()).limit(SESSION_MEMORY_MAX_MESSAGES)`
  then reverses back to chronological order, so a long account conversation rehydrates only its
  most-recent N messages (the same cap as the Redis working memory) instead of its entire
  transcript. Imported `settings` for the cap. No dedicated test added: exercising the cap needs
  >100 persisted messages (heavy for the live-DB suite); the existing ordering integration test
  still passes and confirms the reverse keeps user→assistant order intact.
- **C5 (nit) → fixed (persist on iteration-cap for parity; error paths documented).** The
  iteration-cap path in `stream_turn` (`app/services/chat.py`) now calls
  `await self._persist_turn(user_id, session_id, user_msg, None)` after the `ErrorEvent`, so a
  logged-in user's question is preserved even when the model never produced a final answer —
  parity with the cancel-before-content path. Added a one-line comment on the terminal-error
  handlers documenting their **deliberate** exclusion (an errored turn is a failure and the
  `except` may itself be triggered by a datastore issue, so a DB write there would be futile).
