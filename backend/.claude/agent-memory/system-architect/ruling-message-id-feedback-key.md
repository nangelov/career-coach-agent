---
name: ruling-message-id-feedback-key
description: How the stable §5.5 message_id is scoped as a feedback key, and where durable lookup must live in P2/P9
metadata:
  type: project
---

The stable assistant `message_id` (design §5.5) was formalized in P1-07. Two rulings blessed there that
downstream tasks must honor:

**1. Stamp only the terminal user-facing assistant message.** `ChatService.stream_turn` assigns one uuid4 per
turn and stamps it on the final answer (or the cancelled partial), NOT on intermediate tool-request assistant
messages (which carry no `message_id`). This makes the id a 1:1 handle → exactly one addressable answer.
**Why:** §5.5's "each assistant message" means the response the user sees/reacts to, not internal multi-tool
scaffolding. **How to apply:** when reviewing P2 (`message_feedback` table) and P9
(`POST /api/messages/{message_id}/feedback`), require feedback to key only on terminal answers; do not expect
tool-request messages to be feedback-addressable.

**2. `SessionMemory.get_message` is P1 recoverability plumbing only, NOT durable feedback lookup.** It scans the
Redis session window, which is sliding-TTL + count-capped — a message can age out, after which lookup returns
`None`. **How to apply:** when P2 adds durable Postgres history for logged-in users, feedback lookup-by-id must
resolve against the durable store, not this Redis scan. Flag any P9 design that relies on `get_message` alone
for durable feedback resolution.

The `message_id` field lives on `ChatMessage` (`app/llm/types.py`) but is excluded from `to_openai()` — it must
never enter the provider wire payload. See [[pattern-p1-walking-skeleton]], [[ruling-client-history-trust]]
(client-supplied `history` can now carry a `message_id`; harmless, dropped at `to_openai()`, still a P3 trust item).
