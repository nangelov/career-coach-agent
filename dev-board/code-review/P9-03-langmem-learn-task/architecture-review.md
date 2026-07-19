# Architecture review — P9-03-langmem-learn-task · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | learn domain, task, primitives in the right modules | `memory/learn.py` (domain), `tasks/memory_learn.py` (Celery), write primitives in `repositories/vector_search.py`, store methods in `memory/store.py` | none |
| A2 | Layering (Router→Service→Agent/Repo) | task/store never touch the driver; SQL only in repository layer | store methods wrap `vector_search.py` primitives (open-session, caller-commits); no hand-rolled SQL above repo | none |
| A3 | §5.4 pt3 — learn is async/post-turn via Celery | off request path, never blocks SSE | enqueued after `_persist_turn` on success-only path; `_enqueue_learn` log-never-raise | none |
| A4 | §4 / §5.4 — guests durable-free | no learning for guests | enqueue no-ops on `user_id is None`; core returns `skipped` for malformed uuid | none |
| A5 | §6.7 LangMem | teachable per-user memory over pgvector `user_memories` | hand-rolled extraction instead of `create_memory_store_manager` — **DEVIATION explicitly allowed by task**, and consistent with the already-blessed P9-02 first-party-over-LangMem-manager precedent; confidence + thumb-down are first-party concepts LangMem does not model | accepted, documented in module docstring |
| A6 | Locked: native tool-calling, no ReAct | forced tool-call, no regex parser | `LLMMemoryExtractor` uses forced `record_memories` tool-choice on the shared router | none |
| A7 | Locked: single LLM router, no 2nd client; in-process embeddings; budget | reuse shared router + sentence-transformers | worker builds one `LLMRouter.from_settings` + `SentenceTransformerEmbeddingClient`; no paid/second client | none |
| A8 | §7.3 untrusted-content | user text fenced as data, not instructions | `fence_untrusted("EXCHANGE", …)` around the turn before the forced tool-call | none |
| A9 | Store single-home (P9-02 ruling) | extend `UserMemoryStore` not duplicate | typed `add/update/delete/list_memories_for_message` added in place; P9-05 reuses them | none |
| A10 | §5.5 thumb-down → demote/remove | down-vote demotes/removes attributed memory or learns "don't do X" | `source_message_id`-keyed demotion (confidence − decrement; delete at floor) + explicit negative preference from reason | none |
| A11 | Celery task shape | mirror `profile_ingest.py` | `bind=True` sync task → `asyncio.run`, own composition root, deferred heavy imports, registered in `celery_app.include` | none |
| A12 | P9-04 seam | leave PII/GDPR gate seam, don't build it | `MemoryExtractor.propose` is the single documented wrap point | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (native tool-calling, no ReAct; Postgres+Redis only; in-process embeddings; single router)
- [x] Interfaces-before-implementations (`MemoryWriter` / `MemoryExtractor` / `TurnFeedbackReader` / `LearnEnqueuer` ports; store extended, not duplicated)
- [x] Budget posture respected (free/OSS/self-hosted; no paid or second LLM client)

## Notes
- The LangMem hand-roll (A5) is a task-sanctioned deviation and consistent with the P9-02 ruling — no re-litigation.
- `LLMCompleter` Protocol is re-declared locally in `learn.py` (also present in `planner.py`, `structuring.py`). This is the established structural-port convention (avoids a hard `LLMRouter` import), accepted — not new DRY debt.
- Design risk (non-blocking, code-reviewer's domain): the demotion pass re-scans `list_recent_downvotes` on every learn pass, so a single down-vote can demote the same memory across several subsequent turns until removal. Not an architecture gate; flagged for correctness review / a possible follow-up (mark-demoted idempotency).
