# Task P9-03-langmem-learn-task — post-turn learn step (Celery)
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Implement the **learn** half of the teachable-memory loop (§5.4 point 3): a **Celery task**,
enqueued post-turn for a logged-in user, that extracts durable facts/preferences from the
just-completed exchange, dedupes/updates against existing `user_memories`, assigns confidence,
and folds in thumb-down feedback as a demotion/removal signal.

From `dev-board/tasks.md` (P9):
> Learn step as a Celery task post-turn (LangMem extract/update): durable prefs, dedup/update,
> confidence; thumb-down demotes/removes.

### What already exists (read before building)
- `backend/app/memory/store.py` — `UserMemoryStore(BaseStore)`. **Search-only today**; its
  docstrings explicitly say the write path (`PutOp`/update/delete) is this task's to add. Extend
  it in place (or add sibling methods) rather than duplicating a second store.
- `backend/app/repositories/vector_search.py` — `add_user_memory(session, *, user_id, text,
  embedding, memory_type, confidence=1.0, source_message_id=None)` already inserts a row.
  `memory_type` must be one of the check-constraint values (`preference` / `fact` / `style` —
  see `backend/app/repositories/models/knowledge.py::UserMemory`). There is **no update/delete
  primitive yet** for `user_memories` — add one (e.g. `update_user_memory`,
  `delete_user_memory`) following the same "primitive takes an open session, caller commits"
  convention as the rest of that module.
- `backend/app/agents/memory_agent.py` — `recall(...)` (P9-02) is the read side; this task is
  the write side and should live in its own module (e.g. `backend/app/memory/learn.py` or
  `backend/app/tasks/memory_learn.py` — your call, mirror whichever existing split feels most
  consistent, e.g. agents/services vs tasks/).
- `backend/app/services/message_feedback.py` / `repositories/message_feedback_store.py` (P9-01)
  — `MessageFeedbackStore.list_recent_downvotes(...)` / `get_for_message(...)` already exist,
  built specifically for this task to consume.
- `backend/app/tasks/profile_ingest.py` — the Celery-task pattern to mirror: `bind=True`, sync
  task wrapping an `asyncio.run(...)`-driven async implementation, constructing its own
  DB/embedder/LLM-router inside the worker process (no shared FastAPI `app.state`), heavy
  imports deferred so importing the module stays light. Follow this shape for the new learn
  task rather than inventing a different one.
- `backend/app/services/chat.py::ChatService._persist_turn` — where a completed turn is
  durably persisted for a logged-in user (guests are a no-op here, §4). This is the natural
  enqueue point for the learn task: after a successful, non-cancelled turn, for `user_id is not
  None`, enqueue `learn_from_turn.delay(...)` (or whatever you name it) with the minimum data
  needed (user id, the turn's `message_id`, user text, assistant text) — **do not block the
  SSE response on it**; enqueue is fire-and-forget like the rest of `_persist_turn`'s
  best-effort posture (log, never raise).
- `backend/.venv/lib/python3.11/site-packages/langmem/knowledge/extraction.py` /
  `langmem/knowledge/tools.py` — LangMem's `create_memory_store_manager` (or the lower-level
  extractor) is built to run an LLM extraction pass over `messages` against a `BaseStore` and
  handles de-dup/update itself when pointed at a real store. Wire this against
  `UserMemoryStore` once its write ops are implemented, using the existing LLM router
  (`app.llm.router` / the P1-02 completer) as the extraction model — **no second LLM client**.
  If LangMem's manager proves awkward to point at a partially-custom store, a hand-rolled
  extraction prompt + `add_user_memory` + a similarity-based dedup check
  (`search_memories` above a threshold → update confidence instead of inserting a near-duplicate)
  is an acceptable fallback — note the deviation and why in `engineer.md`.

## Acceptance criteria
- [ ] `UserMemoryStore` (or a documented extension of it) supports **put/update/delete** against
      `user_memories`, reusing/extending the `vector_search.py` primitives (no hand-rolled SQL
      in the agent/task layer).
- [ ] A Celery task (mirroring the `profile_ingest.py` pattern) that, given a completed turn
      (user id, message id, user + assistant text):
      - runs an extraction pass proposing 0+ candidate durable memories (preference/fact/style);
      - **dedupes against existing memories** (similarity search above a threshold updates the
        existing row's confidence/text rather than inserting a near-duplicate);
      - assigns/updates a `confidence` value (not always `1.0`);
      - is a **no-op for chit-chat** — not every turn produces a memory; the extractor is
        expected to often propose nothing.
- [ ] **Thumb-down handling**: when the task runs for a turn that has recent thumbs-down
      feedback (via P9-01's `list_recent_downvotes`/`get_for_message`), it demotes (lowers
      confidence) or removes the memory/memories most associated with that turn's advice,
      and/or can learn an explicit negative preference ("don't do X") — a reasonable, documented
      interpretation of §5.4's "a down-vote can demote/remove a memory or learn an explicit
      'don't do X'" is acceptable; do not over-engineer a perfect signal-attribution model.
- [ ] Enqueued post-turn from `ChatService._persist_turn` (or immediately after it) for
      logged-in users only; guests are a no-op (durable learning requires an account, §5.4).
      Enqueue failures are logged, never raised (must not break the SSE stream).
- [ ] Unit tests for: a turn that yields a new memory (inserted), a turn that yields a near-dup
      of an existing memory (updated, not duplicated), a turn with no learnable content (no-op),
      and a thumbs-down turn (demotion/removal exercised).
- [ ] Integration test (or clearly documented manual steps) exercising the task against a real
      Postgres, matching how other Celery tasks in this repo are verified (see P5/P6 task tests).

## Design references
- dev-board/app-design-and-features.md: §5.4 (Personalization — the teachable agent), point 3
  "Learn (post-turn, async via Celery)"; §5.5 (thumb up/down → learning loop); §6.7 (LangMem).
- dev-board/plan.md: P9.
- `backend/app/agents/memory_agent.py`, `backend/app/memory/store.py` (P9-02 — read side + the
  store this task extends).

## Constraints / non-goals
- **No PII redaction / GDPR Art. 9 exclusion filter yet** — that is the next task (P9-04),
  which will wrap/gate this extraction step. Do not skip writing memories out of caution, but
  also do not build the redaction/exclusion logic here; a follow-up task adds it as an explicit
  gate. (If it is trivial to leave an obvious extension seam — e.g. a single function call site
  the next task will fill in — that's welcome, but not required.)
- No `GET/PUT/DELETE /api/memory` panel — that is P9-05.
- No responder tone/depth adaptation — that is P9-06.
- No guest/Redis personalization — that is P9-07.
- No retention-purge job — that is P9-08.
