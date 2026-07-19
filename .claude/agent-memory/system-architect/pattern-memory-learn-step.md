---
name: pattern-memory-learn-step
description: P9-03 blessed post-turn learn step — hand-rolled extraction over LangMem manager, typed store write path, thumb-down demotion, Celery mirror of profile_ingest
metadata:
  type: project
---

P9-03 (post-turn teachable-memory learn) APPROVED rev 1. Blessed design:

- **Write path extends UserMemoryStore in place** (typed add_memory/update_memory/delete_memory/list_memories_for_message), each wrapping a new vector_search.py primitive (update_user_memory/delete_user_memory/list_user_memories_by_source_message, open-session caller-commits). No hand-rolled SQL above repository layer — conforms to [[pattern-memory-recall-store]] "single home, extend not duplicate".
- **Hand-rolled extraction, NOT LangMem create_memory_store_manager** — task explicitly allowed the fallback, and it is consistent with the already-blessed P9-02 precedent (first-party search over LangMem manager). Confidence + thumb-down demotion are first-party concepts LangMem does not model. Extraction uses native forced tool-call on shared LLM router (no 2nd client, no ReAct) + fence_untrusted (§7.3, [[project-untrusted-content-contract]]).
- **Celery task mirrors profile_ingest.py**: sync task → asyncio.run, own worker composition root (embedder/router/PG/feedback store), deferred heavy imports; injectable core run_learn_from_turn is the testable heart.
- **Enqueue** from ChatService._enqueue_learn after _persist_turn on success-only (not cancelled) logged-in path; guest/no-Postgres/empty-answer = no-op; log-never-raise. LearnEnqueuer narrow callable port.

**Why:** keeps the write path in one store, honors locked native-tool-calling + budget (no paid/2nd client), keeps learning off the request path.

**How to apply:** P9-05 memory-CRUD API reuses the same typed store methods (do not add a parallel write path).

**P9-04 (PII/GDPR §7.6 gate) APPROVED rev 1 — seam relocated & blessed.** Gate landed at `_apply_candidate` (the single write boundary), NOT at `MemoryExtractor.propose` as originally noted. This is stronger and was task-permitted: `_apply_candidate` also covers the down-vote-reason synthesised candidate that never passes through `propose`. New pure `app/memory/gdpr_filter.py` (deterministic regex per Art. 9 category, no ML/NER — same tier as P10 injection classifier, over-drop failure direction); reuses `llm.redaction.redact_contact_details` (not re-implemented). Order = redact-then-classify. Do NOT re-litigate the propose-vs-write-boundary choice for future memory gates: the write boundary is the correct chokepoint.

**Logged non-blocking follow-ups:** (1) LLMCompleter Protocol re-declared locally in learn.py (also in planner.py, structuring.py) — established structural-port convention, accepted, not new DRY debt. (2) Demotion pass re-scans list_recent_downvotes every learn pass, so one down-vote can demote the same memory across several subsequent turns until removal — behavioral/idempotency concern flagged to code-reviewer, not an architecture gate.
