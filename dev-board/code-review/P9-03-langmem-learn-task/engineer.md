# Engineer report — P9-03-langmem-learn-task · Revision 2

## Revision 2 summary (addressing code review)
Made thumb-down demotion **idempotent per down-vote** (code-review **C1**, major) and cleaned up
the dead-compute nit (**C2**). C3 was explicitly "no change required".

- **C1 fix — timestamp-gated demotion (no schema change).** The demotion pass re-scans the
  recent-downvote window every learn pass (a vote arrives *after* the turn's own learn pass), so a
  single standing down-vote previously demoted the same memory on every later turn until deletion.
  Fix: carry `user_memories.updated_at` (already server-maintained via `onupdate=now()`) into the
  demotion projection and **skip any memory whose `updated_at` is strictly after the vote's
  `created_at`** — i.e. a memory learned after, or already demoted in response to, that same vote.
  A demotion moves `updated_at` strictly past the vote, so subsequent passes skip it; a genuinely
  *fresh* re-vote bumps the feedback row's `created_at` again and is honoured. No new column, no
  "processed" side-table — the two timestamps the schema already has carry the signal. Strict `>`
  (not `>=`) so a tie never skips a legitimate first demotion.
- Files touched this revision: `app/repositories/vector_search.py` (+`updated_at` on
  `UserMemoryRecord` and its projection), `app/memory/learn.py` (idempotent `_demote_for_message`,
  C2 clamp moved into the insert branch), `tests/test_memory_learn.py` (fake store now models
  `updated_at`/demotion state across passes + new two-pass idempotency test),
  `tests/test_memory_learn_persistence.py` (new live-DB two-pass idempotency test proving the real
  `onupdate=now()` behavior the fix relies on).
- Tests: `ruff` + `mypy --strict` clean on changed source **and** the two changed test files; full
  suite (live DB) **862 passed, 1 skipped** (was 860 — two new idempotency tests).

## Response to review (revision 1 → 2)
- **C1 (major) — non-idempotent demotion → progressive silent deletion.** Fixed as above:
  `_demote_for_message` now takes the down-vote's `voted_at` and skips memories with
  `record.updated_at > voted_at`. `UserMemoryRecord`/`list_user_memories_by_source_message` now
  project `updated_at`. Added the requested regression test running **two consecutive learn passes
  over the same standing down-vote**, asserting the memory is demoted **once** (0.9→0.6) and never
  driven to deletion — both as a fast unit test (`test_standing_downvote_demotes_once_not_every_pass`)
  and a live-DB test exercising the real `onupdate=now()`
  (`test_standing_downvote_demotes_once_against_real_updated_at`). This also correctly protects the
  freshly-inserted "avoid X" negative-preference memory (its `updated_at` post-dates the vote) from
  being demoted on the next pass.
- **C2 (nit) — dead `initial_confidence` compute on the reinforce branch.** Removed; the
  `_clamp_confidence(...)` call now lives inline in the insert branch (only computed when a row is
  actually inserted).
- **C3 (nit) — synchronous broker round-trip in the async finaliser.** No change required (as the
  reviewer noted); it runs after the terminal `DoneEvent`, is try/except-wrapped, and the
  fire-and-forget posture is intentional. Left as-is.

---

# Engineer report — P9-03-langmem-learn-task · Revision 1

## Summary
Implemented the **learn** half of the teachable-memory loop (§5.4 point 3 / §5.5): the write path
on `UserMemoryStore`, an injectable post-turn learn core (extract → dedupe → confidence + thumb-down
demotion), a Celery task wrapping it (mirroring `profile_ingest.py`), and the fire-and-forget
enqueue from `ChatService` after a successful logged-in turn.

## Files changed
- `backend/app/repositories/vector_search.py` — new `UserMemoryRecord` DTO + `update_user_memory` /
  `delete_user_memory` / `list_user_memories_by_source_message` primitives (open-session, caller
  commits — same convention as the existing helpers). No hand-rolled SQL leaves this layer.
- `backend/app/memory/store.py` — extended `UserMemoryStore` **in place** with typed write methods
  `add_memory` / `update_memory` / `delete_memory` / `list_memories_for_message` (each wraps a
  primitive + owns its commit). Moved the `SessionProvider` import under `TYPE_CHECKING` to break an
  import cycle (see Key decisions).
- `backend/app/memory/learn.py` (new) — the learn domain: `MemoryCandidate`, `LearnConfig`,
  `LearnResult`, the `MemoryExtractor` / `MemoryWriter` / `TurnFeedbackReader` ports, the native
  tool-calling `LLMMemoryExtractor`, and the injectable core `run_learn_from_turn`.
- `backend/app/tasks/memory_learn.py` (new) — Celery `learn_from_turn` task + `enqueue_learn_from_turn`
  + the standalone-worker composition root (builds its own embedder/router/DB/feedback store, heavy
  imports deferred), mirroring `profile_ingest.py`.
- `backend/app/tasks/celery_app.py` — registered `app.tasks.memory_learn` in `include`.
- `backend/app/services/chat.py` — new `LearnEnqueuer` port + `_enqueue_learn` called only on the
  successful (non-cancelled) logged-in path; log-never-raise.
- `backend/app/bootstrap.py` — wire `enqueue_learn_from_turn` into `ChatService` (only when the
  shared Postgres pool exists).
- Tests: `tests/test_memory_learn.py` (unit), `tests/test_memory_learn_persistence.py` (live DB),
  and enqueue tests appended to `tests/test_chat_persistence.py`.

## Key decisions
- **Hand-rolled extraction, not LangMem's `create_memory_store_manager` [DEVIATION — explicitly
  allowed by task].** The store deliberately exposes *typed* write methods, not full generic
  `PutOp`/`DeleteOp` BaseStore semantics; and **confidence** + **thumb-down demotion** are
  first-party concepts LangMem does not model. Pointing the manager at a partially-custom store
  would mean re-implementing generic op surface only to hide it. Extraction still uses **native
  tool-calling** on the shared LLM router (no second client, no ReAct/regex — locked decision),
  mirroring `ProfileStructurer`. Documented in `learn.py`'s module docstring.
- **Thumb-down interpretation (§5.5).** A memory whose `source_message_id` is a turn the user later
  down-voted is attributed to that bad advice and demoted (`confidence -= decrement`); at/below a
  floor it is deleted. Scans both this turn's feedback and the user's recent down-votes
  (`list_recent_downvotes`) — so a down-vote arriving *after* the turn still demotes on the next
  learn pass. A down-voted turn skips positive extraction and, if a reason was given, learns an
  explicit "avoid X" preference — the §5.5 "learn an explicit don't-do-X" option.
- **Confidence is a real signal, never blindly 1.0.** Extractor proposes per-candidate confidence
  (clamped to `[min, 1.0]`, fallback `default_confidence`); a near-duplicate reinforces the existing
  row (`min(1.0, existing + increment)`) instead of inserting a twin.
- **Enqueue point.** After `_persist_turn` on the success branch only (not cancelled), guarded to
  logged-in users with a non-empty answer; fire-and-forget, log-never-raise (§5.4 durable learning
  requires an account; must not block/break the SSE stream).
- **Import-cycle fix.** `store.py` importing `app.agents.rag_agent` at module top closed an
  `agents ↔ memory` cycle once `app.memory` became an import entrypoint (the learn task). The
  symbol is annotation-only → moved under `TYPE_CHECKING`.
- **P9-04 seam left open (not built here).** No PII/GDPR exclusion filter — the single seam the next
  task fills is `MemoryExtractor.propose` (filter its returned candidates), noted in the docstring.

## How to verify
- Unit: `cd backend && .venv/bin/python -m pytest tests/test_memory_learn.py tests/test_chat_persistence.py -q`
- Live DB (docker `career-coach-agent-db-1` up):
  `set -a && . ../.env && set +a && export DATABASE_URL="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB" && .venv/bin/python -m pytest tests/test_memory_learn_persistence.py -q`
- Lint/type: `.venv/bin/ruff check <changed>` · `.venv/bin/mypy <changed source>`

## Tests (final step — mandatory)
- `ruff check` (changed files): **All checks passed!**
- `mypy` (6 changed source files, strict): **Success: no issues found**
- Full suite with live DB: `.venv/bin/python -m pytest -q` → **860 passed, 1 skipped** (the 1 skip
  is a pre-existing unrelated conditional skip; all P9-03 live-DB tests ran and passed).
- One iteration fix during development: the live-DB dedup test initially used a zero embedding →
  pgvector cosine distance is NaN for a zero vector, so the near-duplicate never crossed the
  threshold. Root cause was the **test fixture** (not the code); fixed to a non-zero constant
  embedding (`[0.1]*4096`) and re-ran green.

## Self-check
- [x] Meets acceptance criteria (put/update/delete via primitives; insert / near-dup-update /
      chit-chat no-op / thumb-down demotion+removal covered by unit tests; live-DB integration test;
      enqueued post-turn for logged-in users only, guests no-op, enqueue failures swallowed).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (services/tasks call the
      store/primitives, never the driver).
- [x] Tests/lints/mypy pass (results pasted above).
