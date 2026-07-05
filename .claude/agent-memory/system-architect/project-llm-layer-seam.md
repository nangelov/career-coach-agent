---
name: project-llm-layer-seam
description: Blessed llm/ layer design — LLMClient ABC + first-party types/errors, single-provider client, failover lives only in router.py (P1-02)
metadata:
  type: project
---

**Blessed at P1-01 (LLMClient, approved rev 1).** The `backend/app/llm/` seam pattern gates future LLM tasks:

- `client.py` = `LLMClient` ABC + concrete `HFOpenAICompatibleClient` (openai async SDK against HF base URL). Provider SDK import is **confined to client.py**; callers speak first-party models only.
- Supporting files `types.py` (ChatMessage/ToolCall/CompletionResult/StreamChunk/ToolCallDelta) and `errors.py` (LLMError hierarchy: Timeout/Connection/Response w/ status_code/RateLimit) are an **accepted decomposition** of the §8 `llm/` node — §8 lists client/router/embeddings but is not exhaustive; do NOT flag the extra files as a structure gap.
- **Single client = one model id; `max_retries=0` default.** Failover / retry-across-models / circuit-breaker / mid-stream **resume** (locked #7) belong ONLY to `router.py` (P1-02). Reject any of that logic leaking into the single client.
- The router (P1-02) must branch on the **first-party error types** (status_code exposed), not re-import `openai`. Hold P1-02 to this contract.

**Open follow-up from P1-01 (still open as of P1-09-verify, 2026-07-05):** `LLM_BASE_URL` default is `https://api-inference.huggingface.co/v1` (legacy serverless API, not OpenAI-compatible). HF **Inference Providers** OpenAI-compatible surface is `https://router.huggingface.co/v1` — confirm & retarget the default before P1 is exercised end-to-end against real HF. Ruling: config-driven + one-line + env-overridable = cheap-to-unwind ⇒ APPROVED-with-logged-follow-up, never a CHANGES_REQUESTED gate. Fix is config-default-only; do NOT touch the `llm/` seam.

**Why:** locked decision #2 (native tool-calling, no ReAct parser) + §6.6 (failover lives behind the LLMClient interface). **How to apply:** cite §8 + §6.6 + [[project-v2-locked-stack]] when gating P1-02 router and later agents that consume the client.
