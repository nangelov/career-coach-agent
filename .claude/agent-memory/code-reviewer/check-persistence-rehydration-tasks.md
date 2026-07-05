---
name: check-persistence-rehydration-tasks
description: Reviewing chat-persistence / cache-fallback tasks (P2-07 and later) — the rehydration-not-seeded-back defect and other checks
metadata:
  type: project
---

Reviewing a task that persists chat turns to Postgres and rehydrates context from Postgres when the Redis working memory is empty (P2-07 `ConversationStore`, and any later durable-history work).

**Why:** these tasks have a durable store (Postgres, source of truth) plus a fast cache (Redis `SessionMemory`, bounded + TTL'd). The subtle bug is a **cache-fallback that doesn't repopulate the cache**, which single-turn tests miss.

**How to apply — concrete checks:**
- **Rehydration must seed the cache, not just the turn.** In `ChatService._load_prior`, when it falls back to `ConversationStore.load_history()` (Redis empty), confirm the loaded history is also written back into `SessionMemory` (e.g. `memory.append`). If it only returns it for the current turn's context, the **first** post-restart turn sees full history but the **second** finds Redis non-empty (holding only that one new turn) and skips rehydration → all pre-restart context is silently lost from turn 2 on. This defeats "history survives restart." The P2-07 rev-1 restart test only drove ONE post-restart turn and missed it — always ask for a **two-turn** post-restart test. Reproduce fast with fakes: FakeRouter + FakeConversationStore, persist 2 turns, then a fresh `InMemorySessionMemory` + same store, run two `stream_turn`s, print `router.calls[0]` vs `router.calls[1]`.
- **session_id length contract vs column width.** `ChatRequest.session_id` `max_length` must not exceed `sessions.id` / `conversations.session_id` `String(64)`, else a long id makes `persist_turn` raise and (because persistence is best-effort/swallowed) the turn is silently not persisted. crypto.randomUUID() is 36 chars so it doesn't bite in practice — minor.
- **Best-effort is correctly done here (don't false-positive):** persist happens *after* the terminal `done`/`cancelled` event is yielded, and both persist + rehydrate wrap `except Exception` with logging — that is the intended "never break the SSE stream" posture, not a swallowed-error smell. Guest path (`user_id is None` → no-op) being byte-for-byte unchanged is a real requirement; verify it with an explicit "persists nothing" assertion, not absence of errors.
- **Get-or-create conversation** in the adapter is SELECT-then-INSERT with no unique constraint on `conversations.session_id` — concurrent first-turns could split history. Low-probability nit given one in-flight stream per session; note it.
- **`load_history` has no LIMIT** — Redis is capped by `SESSION_MEMORY_MAX_MESSAGES` but the Postgres rehydration path isn't, so a long transcript can blow the context window after restart. Nit → suggest bounding to the same cap.
- **Live-PG integration tests** for the adapter run against `career-coach-agent-db-1` (migration 0002 applied); set `DATABASE_URL=postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB` from `../.env` and run — they should pass (not skip). Importing `app.*` in a throwaway repro script needs `HF_API_TOKEN`/`DATABASE_URL`/`JWT_SECRET_KEY` env set (Settings() validates at import) and `PYTHONPATH=.:tests`.
