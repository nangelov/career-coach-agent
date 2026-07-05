---
name: project-cache-rehydration-seedback
description: When a service falls back from a cache to a durable store, seed the loaded data back into the cache — else only the first post-miss request sees full context
metadata:
  type: feedback
---

When a service reads from a fast cache (Redis working memory) and, on a miss/empty,
falls back to a durable store (Postgres), it must **write the loaded data back into the
cache** before returning it — not just return it for the current request.

**Why:** In P2-07 chat rehydration, `_load_prior` loaded post-restart history from Postgres
but only appended the *new* turn's messages to Redis. So turn 1 post-restart saw full
history, but turn 2 found Redis non-empty (just turn 1's pair) and skipped rehydration,
silently truncating all pre-restart context. Reviewer flagged it as a gating major.

**How to apply:** Any cache→durable fallback path (session memory, and future
LangMem/embedding caches) should seed the cache with what it rehydrates. Also: a
"rehydrates after restart" feature needs a **multi-turn** test — a single post-restart turn
passes even when turn 2+ is broken. Cap the durable-store read to the same bound as the
cache (e.g. `SESSION_MEMORY_MAX_MESSAGES`) so rehydration doesn't blow the context window.
Keep request-contract field lengths aligned with the DB column widths they land in
(e.g. `ChatRequest.session_id` max_length == `String(64)`), or best-effort inserts silently drop data.
