# Code review — P9-03-langmem-learn-task · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major → **resolved (rev 2)** | `backend/app/memory/learn.py:447-476` (`_demote_for_message`) | Non-idempotent thumb-down demotion: a single standing down-vote stays in the recent-downvote window and re-demoted the same memory on every later learn pass (0.9→0.6→0.3→deleted), silent progressive data loss. | **Fixed.** `_demote_for_message` now takes the vote's `voted_at` and skips any record whose `updated_at > voted_at` (strict `>` so a first-pass tie still demotes once). A demotion bumps `updated_at` (server `onupdate=now()`) strictly past the vote, so every subsequent pass skips it; a genuine re-vote bumps the feedback `created_at` again and is re-honoured. `UserMemoryRecord` / `list_user_memories_by_source_message` now project `updated_at`. Verified by the required two-pass regression test (see Notes). |
| C2 | nit → **resolved (rev 2)** | `backend/app/memory/learn.py:498-503` (`_apply_candidate`) | `initial_confidence` clamp computed before the dedup check, dead on the reinforce branch. | **Fixed.** `_clamp_confidence(...)` now computed inline in the insert branch only; reinforce branch no longer computes it. |
| C3 | nit (accepted) | `backend/app/services/chat.py` enqueue | Synchronous broker round-trip in the async finaliser. | No change required — runs after the terminal `DoneEvent`, try/except-wrapped, fire-and-forget by design. Left as-is (correct). |

## Notes
- **C1 verification.** The guard is sound: memory learned at `t_learn`, down-voted at `t_vote (> t_learn)`; first later pass demotes (`t_learn < t_vote`), bumping `updated_at` to `t_demote > t_vote`; all subsequent passes skip (`t_demote > t_vote`). The freshly-inserted "avoid X" negative-preference memory is likewise protected (its `updated_at` post-dates the vote). The unit test `test_standing_downvote_demotes_once_not_every_pass` (`tests/test_memory_learn.py:455`) asserts pass 1 → `demoted == [mem_id]`, conf 0.9→0.6; pass 2 → `demoted == [] and removed == []`, `deleted == []`, conf held at 0.6. The test is meaningful because `FakeMemoryStore.update_memory` bumps `updated_at=datetime.now(UTC)`, mirroring the real server `onupdate=now()`; a live-DB counterpart (`tests/test_memory_learn_persistence.py:261`) exercises the real `onupdate`.
- Ran locally: `pytest tests/test_memory_learn.py` → 18 passed; `ruff check` + `mypy --strict` clean on `learn.py` + `vector_search.py`. Engineer reports full live-DB suite 862 passed / 1 skipped (was 860 — two new idempotency tests).
- No schema change — the fix rides on the two timestamps already present (`created_at` on feedback, `updated_at` on `user_memories`). Good minimal-footprint choice; no "processed" side-table, no new column.
- Prior-revision good posture unchanged and still holds: enqueue after awaited/committed `_persist_turn` (satisfies the `source_message_id → messages.message_id` FK), fenced + forced-native-tool-call extraction (no free-text escape hatch), per-`user_id` scoping on both the recent-downvote and per-message paths, type-aware dedup, real confidence signal, guest/cancelled/errored/empty/no-enqueuer skip paths tested. PII/GDPR exclusion correctly deferred to P9-04 via the single `MemoryExtractor.propose` seam. No secrets, no arbitrary execution.

## Verdict: APPROVED
