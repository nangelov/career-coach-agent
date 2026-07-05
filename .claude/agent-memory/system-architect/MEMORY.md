# Memory index

- [v2 locked stack](project-v2-locked-stack.md) — the 9 pre-work decisions (GLM-5.2, Qwen3-Embedding-8B dim=4096, LangMem, self-host, guest 10msg+1doc, resume); all 9 now LOCKED (#8 = silent-but-viewable/deletable memory, opt-out)
- [LLM layer seam](project-llm-layer-seam.md) — blessed llm/ pattern (P1-01): LLMClient ABC + first-party types/errors, single client max_retries=0, failover/resume only in router.py (P1-02)
- [Frontend path](project-frontend-path.md) — RESOLVED P0-13: v2 now at canonical §8 frontend/ (renamed from frontend-v2/); v1 CRA in legacy-code/; package.json name still -v2 (cosmetic)
- [Frontend SSE pattern](project-frontend-sse-pattern.md) — blessed P1-08 layering: transport in lib/, UI in components/, thin app/; typed union mirrors backend schemas/chat.py; POST-SSE via fetch not EventSource
