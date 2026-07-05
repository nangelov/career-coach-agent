# Memory index

- [v2 locked stack](project-v2-locked-stack.md) — the 9 pre-work decisions (GLM-5.2, Qwen3-Embedding-8B dim=4096, LangMem, self-host, guest 10msg+1doc, resume); all 9 now LOCKED (#8 = silent-but-viewable/deletable memory, opt-out)
- [LLM layer seam](project-llm-layer-seam.md) — blessed llm/ pattern (P1-01): LLMClient ABC + first-party types/errors, single client max_retries=0, failover/resume only in router.py (P1-02)
- [Frontend path](project-frontend-path.md) — RESOLVED P0-13: v2 now at canonical §8 frontend/ (renamed from frontend-v2/); v1 CRA in legacy-code/; package.json name still -v2 (cosmetic)
- [Frontend SSE pattern](project-frontend-sse-pattern.md) — blessed P1-08 layering: transport in lib/, UI in components/, thin app/; typed union mirrors backend schemas/chat.py; POST-SSE via fetch not EventSource
- [ORM models layout](project-orm-models-layout.md) — blessed P2-03: repositories/models/<group>.py subpackage + identity schema rulings (no password, message_id String(32), feedback SET NULL) for P2-04/05 consistency
- [Hybrid search](project-hybrid-search.md) — blessed P2-06: RRF blend (caller-configurable weights), injectable encoder seam, vector-only user_memories, repo→llm injected not imported; for P2-exit/P4/P5
- [Conversation persistence](project-conversation-persistence.md) — blessed P2-07: ConversationStore port + Postgres adapter, interim user_id seam (non-authZ, P3), best-effort persist-after-terminal + Redis-empty rehydrate, guests Redis-only
- [Phase-exit verification](project-phase-exit-verification.md) — blessed P2-08 pattern for (T) tasks: tests-only, drive real seams, cite prior tests + close only genuine gaps, skip-not-fail live-DB, no product surface
- [CR-01 audit rulings](project-cr01-audit-rulings.md) — rev 2 APPROVED, A3-A8 closed; blessed bootstrap.py root + AppStateKeys + _mixins; P3: remove client user_id, warm Redis eagerly
