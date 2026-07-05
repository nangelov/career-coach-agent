# Engineer report — P1-07-message-id · Revision 1

## Summary
Formalized the ad-hoc SSE `message_id` (P1-04/P1-06) into a genuinely **stable,
feedback-ready** identifier per design §5.5 ("each assistant message carries a stable
`message_id`"). Before this task the id lived **only** in the SSE event payloads
(`start`/`done`/`cancelled`) and was lost the moment a turn was persisted to session
memory — there was no way to look up the assistant message a 👍/👎 refers to.

Now the turn's `message_id` is **stamped onto the persisted user-facing assistant
message** so it survives a round trip through `SessionMemory` and is recoverable later,
without building any feedback storage (that stays P2/P9). The id is still generated
exactly once per turn, is identical across every `message_id`-bearing SSE event, and is
**excluded from the LLM provider payload** (`ChatMessage.to_openai()`).

No new SSE event types, no schema-breaking changes, no Postgres — Redis-only session
memory as before.

## Files changed
- `app/llm/types.py` — added `message_id: str | None = None` to `ChatMessage`. It is a
  first-party feedback id (§5.5); `to_openai()` already whitelists wire fields, so the
  new field is **never** emitted to the provider. Documented that exclusion inline.
- `app/services/chat.py` — stamp the turn's `message_id` onto the **terminal
  user-facing** assistant message in both the plain-answer (`done`) path and the
  cancelled-partial path. Intermediate tool-request assistant messages deliberately
  carry **no** id (kept as internal scaffolding) so the id is a 1:1 handle for the
  answer the user actually reacts to. Clarified the single generation point.
- `app/services/session_memory.py` — added a concrete `SessionMemory.get_message(
  session_id, message_id)` accessor on the ABC (built on `load()`), so **both**
  `InMemorySessionMemory` and `RedisSessionMemory` gain lookup-by-id with **no schema
  change** and no per-implementation override. This is the plumbing P9 keys off.
- `app/schemas/chat.py` — updated the module docstring: `message_id` is now the stable
  §5.5 id (assigned once, identical across events, persisted, never sent to the
  provider) rather than "P1-07 will formalize".
- `tests/test_message_id.py` — **new.** 9 tests against fakes (no HF/Redis network).

No changes to `llm/client.py`, `llm/router.py`, `repositories/redis.py`, `api/chat.py`,
or the SSE vocabulary — the id plumbing sits behind the existing seams.

## Key decisions
- **Field on `ChatMessage`, not a wrapper/sidecar** (task offered both). `SessionMemory`
  persists `ChatMessage.model_dump_json()`; a field round-trips through that for free and
  keeps the `SessionMemory` interface (`list[ChatMessage]`) unchanged. The one risk the
  task flagged — leaking into the provider payload — does not occur because
  `to_openai()` explicitly whitelists fields (`role`/`content`/`name`/`tool_calls`/
  `tool_call_id`); the sole provider path is `client._to_message_params` →
  `to_openai()`. A regression test pins this (`test_message_id_excluded_from_to_openai`
  + `test_message_id_never_sent_to_provider_across_turns`).
- **Stamp only the terminal, user-facing assistant message** (final answer, or the
  cancelled partial), not the intermediate tool-request assistant messages. This keeps
  `message_id` an unambiguous 1:1 key → exactly one stored assistant message, which is
  what P9's `POST /api/messages/{message_id}/feedback` needs. §5.5's "each assistant
  message" is the response the user sees, not internal multi-tool scaffolding.
- **Single generation point unchanged.** `message_id = uuid4().hex` is still assigned
  once at the top of `stream_turn` and reused for `start`, `done`, `cancelled`, and the
  persisted answer — never regenerated across `token`/`tool_call`/`tool_result` inside
  the turn. uuid4 gives uniqueness across turns and sessions (verified by tests).
- **Cancelled partial keeps the streamed id.** The partial assistant message persisted
  on a mid-completion cancel (P1-06 path) is stamped with the same `message_id` it
  streamed under, so feedback on a cut-off answer resolves correctly. (A cancel that
  lands *between* tool round-trips has no partial answer to stamp — nothing the user saw
  to react to; acceptable and documented.)
- **Accessor on the ABC, implemented over `load()`.** A default method (not abstract)
  means it needs no Redis/JSON-specific code and works for every current and future
  `SessionMemory` — a scan over the already-bounded recent-turns history. It is
  recoverability plumbing only, not feedback storage (P2/P9).

## How to verify
From `backend/` (curated env: fastapi/pydantic/openai/redis present):
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/
.venv/bin/python -m pytest -q
```
Results (local `.venv`):
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `44 files already formatted`
- `mypy app/` → `Success: no issues found in 31 source files`
- `pytest -q` → `71 passed` (62 prior + 9 new)

New tests (`tests/test_message_id.py`) map to the acceptance criteria:
- `test_message_id_identical_across_all_sse_events_of_a_turn` — one id on `start` ↔
  `done`.
- `test_message_id_stable_across_a_tool_call_turn` — one id spans a multi-iteration
  (tool round-trip) turn.
- `test_two_turns_same_session_get_distinct_ids` /
  `test_two_sessions_get_distinct_ids` — uniqueness across turns and sessions.
- `test_message_id_round_trips_through_in_memory_store` — id recoverable from the stored
  assistant message + via `get_message()`; miss returns `None`.
- `test_message_id_survives_redis_json_round_trip` — id survives the Redis store's
  `model_dump_json` → `model_validate_json` (not just object identity).
- `test_cancelled_partial_keeps_streamed_message_id` — cancelled partial persists with
  the streamed id (`start` ↔ `cancelled`).
- `test_message_id_excluded_from_to_openai` /
  `test_message_id_never_sent_to_provider_across_turns` — id never in the provider wire
  payload, even when a later turn replays a stored (stamped) assistant message.

## Self-check
- [x] `message_id` generated once per turn, identical across all its SSE events
  (`start`, `done`, `cancelled`).
- [x] `message_id` survives `SessionMemory` `append` → `load` (in-memory and Redis JSON
  paths) and is recoverable via `get_message()`.
- [x] Uniqueness across turns and sessions (uuid4; ≥2-turn / ≥2-session tests).
- [x] Cancelled turn's persisted partial keeps the same id it streamed under.
- [x] `message_id` never leaks into the LLM provider payload (`to_openai()` whitelist;
  regression-tested).
- [x] Unit tests pass with fakes/doubles — no real HF/Redis network.
- [x] `ruff` + `mypy --strict` clean (output pasted).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (id logic in
  `services/`, accessor on the `SessionMemory` port, no datastore driver touched).

## Notes for reviewers
- **Constraints honored:** no `message_feedback` table / feedback endpoint (P2/P9), no
  Postgres, no new/changed SSE event names or shapes. `token`/`tool_call`/`tool_result`
  events are unchanged (they carry no `message_id` — the task's "same id on every event"
  applies to the id-bearing events; adding it to token events would be a shape change the
  constraints forbid).
- **Cancel-between-tool-calls edge:** if a cancel is observed at an iteration boundary
  (no content streamed that iteration), there is no partial assistant message to stamp,
  so `get_message(message_id)` returns `None` — there was nothing the user saw to react
  to. Documented in `chat.py`; acceptance criterion covers only the partial-*message*
  case.
- **`ChatRequest.history`** can now carry a client-supplied `message_id`; harmless (it is
  dropped at `to_openai()` and only the server stamps ids on produced answers). The
  broader "constrain accepted client history" concern remains a P3 trust-boundary item
  (flagged in P1-05), untouched here.
