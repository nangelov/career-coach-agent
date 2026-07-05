# Task P2-07-persist-conversations — Persist chat to Postgres for logged-in users
- **Phase:** P2   **Status:** ENG   **Tags:** (B)

## Scope
Wire the P1 chat pipeline (`ChatService`, `POST /api/chat`) to **durably persist conversations/messages to
Postgres for logged-in users**, using the schema P2-03 already built (`sessions`, `conversations`,
`messages`). **Guests stay Redis-only** — no persisted history (§4: *"Guests get NO persisted history"*).
This is the task the next `(T)` exit-verify item ("Restart app → account chat history intact") depends on.

### The auth gap (read this first)
**Real auth/SSO doesn't exist yet — that's P3.** There is currently no `user_id` anywhere in the request
path; `ChatRequest.session_id` is a client-generated opaque string (P1-08's `crypto.randomUUID()`) with no
notion of "logged in." Follow the same **interim-seam** pattern P1-04 used for session memory (documented
in `app/schemas/chat.py`'s `ChatRequest` docstring: *"P1-05 swaps in a Redis-backed store behind the same
interface without changing this public contract"*):
- Add an **optional** `user_id: str | None = None` field to `ChatRequest` (or an optional header —
  document whichever you choose and why) as an **explicit, documented stand-in** for the real
  JWT-derived identity P3 will provide. When `user_id` is `None` → guest → Redis-only (current P1
  behavior, unchanged). When `user_id` is set → treat as "logged in" → also persist to Postgres.
- Do not build any login/session-creation endpoint here (P3's job). Do not skip this task waiting for
  P3 — the persistence plumbing and its Postgres schema usage can and should be proven now, independent of
  how `user_id` eventually gets populated.

## Build
1. **A `ConversationStore` port** (ABC, `app/services/` — e.g. `conversation_store.py`, alongside
   `session_memory.py`/`cancellation.py`) with an interface such as:
   - `async def persist_turn(self, *, user_id: str, session_id: str, conversation_id: str | None, user_message: ChatMessage, assistant_message: ChatMessage) -> str` (returns the `conversation_id`, creating one on first turn of a session if not supplied),
   - `async def load_history(self, *, user_id: str, session_id: str) -> list[ChatMessage]` (used to
     rehydrate context after a restart, when Redis session memory is empty/expired but Postgres has it).
   Exact method names/shapes are your call — mirror the `SessionMemory`/`CancelRegistry` ports-and-adapters
   shape (interface in `services/`, concrete adapter in `repositories/`).
2. **`PostgresConversationStore`** in `app/repositories/postgres.py` (or a new
   `app/repositories/conversation_store.py` if that keeps `postgres.py` from growing unwieldy — document
   your choice) implementing the port using the P2-03 ORM models (`Session`, `Conversation`, `Message` from
   `app.repositories.models.identity`) via the shared `AsyncEngine`/`async_sessionmaker` from P2-01 (`Base`,
   `PostgresConnectionProvider` — reuse `get_db_session` or a similar session-acquisition path; do not open
   ad-hoc connections).
3. **Wire into `ChatService`** (`app/services/chat.py`): after a turn completes successfully (the same
   point where the assistant's final message is appended to `SessionMemory`, per P1-05/07), if `user_id` is
   present, also call `ConversationStore.persist_turn(...)` with the user's message and the final assistant
   message (carrying its `message_id`). Do this **without blocking the stream** unacceptably — persisting
   after the terminal event has been prepared/queued is fine; document your exact ordering choice
   (e.g. "persist happens after `done`/`cancelled` is yielded, best-effort, logged on failure — a
   persistence failure must never break the user-visible stream").
   - Also persist on `cancelled` (partial-answer) turns, consistent with how `SessionMemory` already
     persists partial answers on cancel (P1-06/07) — a cancelled turn's partial content should not be lost
     for logged-in users either.
4. **Restart rehydration:** when a request arrives for a `user_id`+`session_id` combination and the Redis
   `SessionMemory.load()` returns empty (fresh Redis / TTL expired / app restarted), fall back to
   `ConversationStore.load_history()` to seed the turn's context — this is what makes "chat history
   survives restart for accounts" true. Wire this at the point `ChatService` currently calls
   `SessionMemory.load()` (or in `app/api/chat.py`'s `build_chat_service`/request handling — your call,
   document it).
5. Update `app/api/chat.py`'s wiring (`build_chat_service`, `get_chat_service`) to construct/inject the
   `ConversationStore` alongside the existing `SessionMemory`/`CancelRegistry`, sourcing the Postgres
   provider from `app.state` (P2-01's `PostgresConnectionProvider`), same pattern as Redis providers.

## Verification
- Live-Postgres integration test: drive a fake "logged-in" `ChatService` turn (inject a stub `LLMClient` as
  existing chat-service tests already do) with a `user_id` set, assert a `conversations` row + `messages`
  rows land in Postgres with the correct `message_id`/`role`/`content`.
- **Restart simulation:** persist a turn for a `user_id`, then construct a **fresh** `SessionMemory`
  (simulating Redis having lost the key / app restart) and confirm `ChatService`/the load path rehydrates
  the prior turn from `ConversationStore` rather than starting with empty context.
- **Guest isolation:** confirm a turn with no `user_id` writes **nothing** to Postgres (guest stays
  Redis-only) — an explicit assertion, not just an absence of errors.
- Existing P1 tests (`test_chat_service.py`, `test_chat_api.py`, etc.) must still pass unchanged in
  behavior for the guest path — persistence is additive, not a behavior change for existing flows.
- `ruff` + `mypy` clean.

## Acceptance criteria
- [ ] `ChatRequest` gains a documented, optional `user_id` (or equivalent) interim field; guest behavior
      (no `user_id`) is byte-for-byte unchanged from P1.
- [ ] A `ConversationStore` port + `PostgresConversationStore` adapter exist, following the established
      ports-and-adapters convention.
- [ ] Logged-in turns (including cancelled/partial ones) persist to `conversations`/`messages` using the
      P2-03 schema; guest turns persist nothing to Postgres.
- [ ] A restart-simulation test proves account history rehydrates from Postgres when Redis session memory
      is empty.
- [ ] Persistence failures are logged and never break the user-visible SSE stream (documented + tested).
- [ ] `ruff` + `mypy` clean; full existing test suite still green.

## Design references
- dev-board/app-design-and-features.md §4 ("Guests get NO persisted history"), §9 (API surface)
- dev-board/code-review/P2-03-migration-identity/engineer.md — the `sessions`/`conversations`/`messages`
  ORM models and their field shapes (`message_id` as the natural key, `role` check constraint, cascades)
- dev-board/code-review/P2-01-repositories/engineer.md — `PostgresConnectionProvider`/`get_db_session`,
  the only sanctioned way to acquire a Postgres session
- dev-board/code-review/P1-05-session-memory/engineer.md, P1-07-message-id/engineer.md — the existing
  Redis `SessionMemory` persistence-on-cancel precedent this task extends to Postgres
- backend/app/schemas/chat.py — `ChatRequest`'s existing "interim shape" framing (P1-04), the precedent for
  adding another interim field here

## Constraints / non-goals
- No real auth/SSO/session-creation endpoints — that's P3. `user_id` here is a documented, temporary
  stand-in populated however the caller likes (tests, a future P3 dependency will set it from a verified
  JWT).
- No conversation-history UI (listing past sessions, resuming an old conversation in the frontend) — this
  task is backend persistence plumbing only.
- No changes to the SSE event vocabulary or wire format (schemas/chat.py's `ChatEvent` union stays as-is
  apart from the new optional request field).
