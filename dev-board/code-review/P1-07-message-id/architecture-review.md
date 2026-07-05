# Architecture review — P1-07-message-id · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §5.5 stable `message_id` | Each assistant message carries a stable, feedback-ready `message_id`, assigned once per turn, identical across id-bearing SSE events, recoverable after persistence | Single generation point at top of `stream_turn` (`services/chat.py:187`); reused for `start`/`done`/`cancelled` and stamped on the persisted answer; survives the `SessionMemory` round trip | None — conforms |
| A2 | §8 target structure | Id logic in the right module; provider vocabulary stays in `llm/` | `message_id` field added to `ChatMessage` in `llm/types.py`; turn/stamping logic in `services/chat.py`; lookup accessor on the `SessionMemory` ABC (`services/session_memory.py`) | None — correct module placement |
| A3 | §8 layering + [[ruling-session-memory-placement]] | Repositories own DB access; services depend on the ABC, not the engine | `get_message` added as a **default** ABC method built over `load()` (no driver code); concrete `RedisSessionMemory` stays in `repositories/redis.py` and inherits it unchanged | None — layering respected; no Redis client touched in `services/` |
| A4 | §6/§6.6 native tool-calling, no ReAct | Id must not leak into the provider wire payload | `to_openai()` whitelists `role`/`content`/`name`/`tool_calls`/`tool_call_id`; `message_id` deliberately excluded and regression-pinned | None — no wire leak |
| A5 | §4 data ownership, Redis-only at P1 | No Postgres; whatever is persisted to Redis carries the id | `ChatMessage.model_dump_json()` → `model_validate_json()` round-trips the field through the Redis list store; no `message_feedback` table, no endpoint | None — scope honored |
| A6 | Interface-before-implementation | Lookup plumbing available to all `SessionMemory` impls without a schema change | ABC default method → both `InMemorySessionMemory` and `RedisSessionMemory` gain lookup-by-id for free | None — correct seam |
| A7 | Phase fit (P1 walking skeleton) | No premature coupling to P2/P4/P9; SSE vocabulary unchanged | No new/renamed SSE events; `token`/`tool_call`/`tool_result` untouched; only recoverability plumbing, not feedback storage | None — stays in phase; see N1/N2 |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — id on `ChatMessage` (llm/), loop stamping in services/, concrete store in repositories/.
- [x] Honors locked decisions — no ReAct parser touched; Redis-only (no Postgres); native tool-calling wire payload uncontaminated by `message_id`.
- [x] Interfaces-before-implementations — accessor on the `SessionMemory` port benefits every implementation.
- [x] Budget posture respected — no new services, no paid dependency.

## Notes
- **N1 (design interpretation, blessed):** the engineer stamps the id on **only the terminal user-facing assistant message**, not the intermediate tool-request assistant scaffolding. This is the correct reading of §5.5 for a feedback key (a 1:1 id → exactly one addressable answer) and aligns with P9's `POST /api/messages/{message_id}/feedback`. **P2 (`message_feedback` table) and P9 (endpoint) must key only on terminal answers** — intermediate tool-request messages intentionally carry no id. Logged so this stays consistent; do not re-litigate.
- **N2 (follow-up for P2/P9, not a gate here):** `get_message` scans the **sliding-TTL, count-capped** Redis session window. That is correct as P1 recoverability plumbing (task scope), but it is not a durable feedback lookup — a message can age out of the window (TTL lapse or the `max_messages` trim), after which `get_message` returns `None`. When P2 introduces durable Postgres history for logged-in users, feedback lookup-by-id must resolve against the durable store, not this scan. Flagged for P2/P9; no change required now.
- **N3 (consistency with [[ruling-client-history-trust]]):** `ChatRequest.history` can now also carry a client-supplied `message_id`. It is harmless today — dropped at `to_openai()`, and only the server stamps ids on produced answers — so this task introduces **no new** trust-boundary gap. The existing requirement to constrain accepted client `history` (reject client `system`/`tool` roles + forged `tool_calls`) remains a **live P3 item** per the P1-05 ruling; it is neither worsened nor addressed here. Do not silently bless past P3.
