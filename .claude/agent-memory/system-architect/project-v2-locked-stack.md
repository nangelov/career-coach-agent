---
name: project-v2-locked-stack
description: The 9 locked v2 pre-work decisions (models, embedding dim, LangMem, self-host, guest limits, resume) for conformance gating
metadata:
  type: project
---

The 9 pre-work decisions were locked on 2026-06-28 (design §6 / CLAUDE.md). Gate conformance against these:

1. Orchestration = **LangGraph** (hand-rolled rejected).
2. Primary LLM = **`zai-org/GLM-5.2`** (HF Inference Providers, OpenAI-compatible, native tool-calling).
3. Embeddings = **`Qwen/Qwen3-Embedding-8B`** in-process via sentence-transformers; **output dim = 4096** → pgvector columns MUST be **`vector(4096)`** (`kb_chunks`, `user_memories`). Reject migrations using any other dim or a placeholder `vector(N)`.
4. Failover secondary = **`Qwen/Qwen3.6-27B`**; **no paid last-resort**.
5. Guest rate-limit = **10 messages + 1 document upload per guest session** (Redis-enforced).
6. Teachable memory = **LangMem** (in-process, over pgvector `user_memories`). This **supersedes** the earlier "custom pgvector" [DECIDED]. Reject hand-rolled recall/learn/dedup modules when LangMem should be used.
7. Mid-stream failover = **resume** on the secondary model (NOT restart-with-notice). Reject restart-with-notice implementations.
8. Learned-memory application = **silent-but-viewable/deletable (opt-out)** — LOCKED 2026-06-28 by product owner. LangMem extracts & applies learned facts automatically WITHOUT per-fact confirmation prompts; user can view & delete via a memory panel. Reject any P9 implementation that gates each learned fact behind a user-confirmation/opt-in step. A view+delete UI over `user_memories` IS required (the "viewable/deletable" half is part of the locked decision, not optional).
9. Datastores = **Postgres + Redis only, self-hosted** (docker-compose local + co-located on Spaces); **no managed tier** (Neon/Supabase/Upstash) for now — managed tier is only a documented escape hatch behind `repositories/`.

**Why:** product owner locked these to unblock P1 (migrations depend on the vector dim; foundation depends on model/orchestrator choices).
**How to apply:** cite the specific decision when gating; the pgvector dim (4096) and the LangMem-over-custom supersession are the two most likely to be implemented wrong.
