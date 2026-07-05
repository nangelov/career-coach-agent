---
name: project-conversation-persistence
description: Blessed P2-07 durable-chat pattern — ConversationStore port + Postgres adapter, interim user_id seam, best-effort persist/rehydrate
metadata:
  type: project
---

Blessed P2-07 (persist conversations to Postgres for logged-in users).

**Fact:** Durable chat history follows the same ports-and-adapters shape as
[[project-orm-models-layout]] and session memory: `ConversationStore` ABC in
`app/services/conversation_store.py`, `PostgresConversationStore` adapter in
`app/repositories/conversation_store.py` (its own module, not swelling `postgres.py`), over
the P2-01 shared `PostgresConnectionProvider.session()` and the P2-03 identity models.

**Why:** §4 "Guests get NO persisted history" — logged-in users' turns must survive restart/Redis
eviction; guests stay Redis-only. Interfaces-before-implementations keeps the service on the port.

**How to apply (rulings to keep consistent):**
- **Interim `user_id` seam is blessed.** Real auth is P3; `ChatRequest.user_id: str | None` is a
  documented, non-authorization stand-in for the P3 JWT-derived `users.id`. `None`→guest (Redis-only),
  set→logged-in (also Postgres). Follows the P1-04 interim-field precedent. Do not re-litigate; do NOT
  treat it as an authZ boundary until P3 populates it from the verified JWT.
- **Best-effort persistence is required, not optional.** Persist happens AFTER the terminal
  `done`/`cancelled` SSE event is yielded; persist + Postgres rehydrate are wrapped best-effort (logged,
  swallowed) — a DB failure must never break the user-visible stream. Cancelled/partial turns persist too.
- **Rehydrate only when Redis empty AND user_id set** (fresh Redis/TTL/restart) — that's what makes account
  history survive restart.
- **Durable store is intentionally lossy on tool scaffolding:** only user + final/partial-assistant messages
  are stored (turn `message_id` preserved per §5.5); tool round-trips stay in Redis working memory only.
- **Open follow-ups (noted, not gated):** `ChatRequest.session_id` max_length=200 vs `Session.id` String(64)
  mismatch; message ordering relies on per-turn `created_at`+role_rank (no sequence column) — revisit if P4
  trace persistence needs an explicit ordinal.
