# Task P1-07-message-id — stable `message_id` on every assistant message
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Formalize the `message_id` that P1-04/P1-06 already generate ad hoc for SSE framing (`start`/`done`/
`cancelled` events currently carry a per-turn UUID hex) into a genuinely **stable** identifier per design
§5.5: *"Each assistant message carries a stable `message_id`"* — the foundation `POST
/api/messages/{message_id}/feedback` (P9) and the Postgres `message_feedback` table (P2) will key off.

Today (read `dev-board/code-review/P1-04-chat-endpoint/engineer.md` and
`dev-board/code-review/P1-06-cancel-stream/engineer.md` first), the id lives **only in the SSE event
payloads** — `app/llm/types.py`'s `ChatMessage` has **no `message_id` field**, so once a turn is appended to
`SessionMemory` (P1-05's `RedisSessionMemory`) the id is lost; it isn't retrievable from the persisted
message itself. Close that gap:

- Add a `message_id` field to the persisted representation of an assistant message so it survives being
  written to and read back from session memory — either by extending `ChatMessage` itself (careful: it's
  also the wire vocabulary sent *to* the LLM provider in `to_openai()`; a `message_id` must **not** leak into
  the provider payload) or by carrying it alongside `ChatMessage` in whatever `SessionMemory`/`ChatService`
  data structure represents a stored turn (e.g. a small wrapper/tuple, or a sidecar dict keyed by id) — your
  call, but the id must be recoverable later for a given assistant message without re-deriving it.
- Assign the id **once per assistant turn**, at the start of that turn's generation (this already happens in
  `ChatService` — verify it's a single generation point, not scattered, and that it's never regenerated
  mid-turn across `start`/`token`/`tool_call`/`tool_result`/`done`/`cancelled` events for the same turn).
- Guarantee **uniqueness** across turns and across sessions (UUID4 is fine — confirm the current approach
  already gives this, or fix it if not).
- Make sure a **cancelled** turn's partial assistant message (persisted per P1-06) keeps the *same*
  `message_id` it streamed under — a user reacting 👍/👎 to a cut-off answer later must reference the id they
  actually saw.
- Add a small accessor/helper if useful (e.g. on `SessionMemory` or `ChatService`) for "get the stored
  message by `message_id`" — not full feedback storage (that's P2/P9), just make sure the plumbing supports
  looking a message up by its id later without a schema change.
- Tests: assert the same `message_id` appears on every SSE event for one turn (`start` → `token`* →
  `done`/`cancelled`), that two different turns (including two turns in the same session) get different
  ids, that the id round-trips through `SessionMemory.load()` after `append()`, and that `message_id` never
  appears in the payload sent to the LLM provider (`ChatMessage.to_openai()` / the request body the client
  actually sends).

## Acceptance criteria
- [ ] `message_id` is generated exactly once per assistant turn and is identical across all SSE events for
      that turn (`start`, `done`, or `cancelled` for the cancelled case).
- [ ] `message_id` survives a round trip through `SessionMemory` (`append` → `load`) — it's recoverable from
      the stored message, not only from the live SSE stream.
- [ ] Uniqueness holds across turns and sessions (test with ≥2 turns / ≥2 sessions).
- [ ] A cancelled turn's persisted partial message keeps the same id it streamed under.
- [ ] `message_id` never leaks into the wire payload sent to the LLM provider.
- [ ] Unit tests pass (fakes/doubles — no real network/Redis needed beyond what P1-05/P1-06 already use).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/app-design-and-features.md: §5.5 Response feedback (stable `message_id` requirement), §4
  `message_feedback` table (future consumer, P2/P9), §9 `POST /api/messages/{message_id}/feedback` (future
  consumer, P9)
- dev-board/code-review/P1-04-chat-endpoint/engineer.md — where `message_id` currently originates (SSE
  `start`/`done` events) and the note "P1-07 formalizes the stable, feedback-ready semantics"
- dev-board/code-review/P1-06-cancel-stream/engineer.md — the `cancelled` event's `message_id` and partial
  message persistence path
- dev-board/code-review/P1-05-session-memory/engineer.md — `SessionMemory`/`RedisSessionMemory` — where the
  id needs to survive a round trip

## Constraints / non-goals
- No `message_feedback` table or `POST /api/messages/{message_id}/feedback` endpoint here (P2/P9) — this
  task only makes the id stable, unique, and recoverable; it does not build feedback storage.
- No Postgres work (P2) — session memory stays Redis-only at this phase; just make sure whatever gets
  persisted there carries the id.
- Don't change the SSE event *names*/shape beyond what's needed to keep `message_id` consistent (P1-04/P1-06
  already defined the vocabulary — this task should not need to add new event types).
