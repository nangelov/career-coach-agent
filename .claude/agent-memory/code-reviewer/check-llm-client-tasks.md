---
name: check-llm-client-tasks
description: How to review P1 LLM-layer tasks (client/router/embeddings) — openai SDK isolation, native tool-calling, error translation, mocked-transport tests
metadata:
  type: project
---

Review checklist for `backend/app/llm/` tasks (P1-01 client done; P1-02 router, embeddings next).

**Why:** These tasks carry locked v2 decisions (native tool-calling deletes the v1 ReAct parser; primary `zai-org/GLM-5.2` via HF OpenAI-compatible endpoint; failover lives only in `router.py`). Design §6 item 6 + §6.6.

**How to apply:**
- **Provider SDK isolation:** `openai` (or `huggingface_hub`) may only be imported inside `client.py`. Callers depend on the `LLMClient` ABC + first-party `types.py`/`errors.py`. Grep the diff for `import openai` outside `client.py` → gate if leaked.
- **No ReAct/regex text parsing** anywhere in the new path — tool calls must be read structurally from `tool_calls`. Flag any regex over model output.
- **Error translation order matters:** in the openai SDK, `APITimeoutError ⊂ APIConnectionError` and `RateLimitError ⊂ APIStatusError`. Most-specific `isinstance` must be checked first, else timeouts/rate-limits get mis-mapped.
- **Streaming is an async generator:** the `await ...create(stream=True)` is deferred to first `__anext__`; confirm both open-time and mid-stream exceptions are translated, and that `except LLMError: raise` guards against double-wrapping.
- **Scope discipline:** the single client must NOT contain failover/retry/circuit-breaker (that's `router.py`); expect `max_retries=0`. Router P1-02 wraps an ordered list of clients.
- **Tests:** must use `httpx.MockTransport` (no network). Verify the 4 required cases: plain completion, tool-call round trip, streaming (content + tool deltas), timeout→`LLMTimeoutError`. Env secrets seeded via `conftest.py` `os.environ.setdefault`.
- **Verify runner:** `cd backend && uv run --no-sync pytest -q tests/... && uv run --no-sync ruff check . && uv run --no-sync mypy app/`. `openai` is pinned `>=2.0` (uses the `omit` sentinel, not legacy `NOT_GIVEN`) and is added to the curated CI install in `.github/workflows/backend-ci.yml`.
- **Router (P1-02) specifics:** circuit-breaker is Redis-injected via a `RedisLike` structural Protocol (no `redis` import in router.py, no new CI dep — tests use an in-memory FakeRedis). Same-model retry (transient 5xx/429) is distinct from cross-model failover; a 4xx-non-429 must NOT fail over (fails on every model). Mid-stream resume prefills the buffered partial as a trailing `assistant` message and yields only the continuation. **Watch:** that resume correctness depends on the HF endpoint honoring a trailing partial-assistant message as a continuation prefix — many OpenAI-compatible servers instead start a fresh turn (needs a `continue_final_message`/`prefix` flag), which would duplicate/re-greet in prod. It's design-§6.6-locked and mock-tested at this layer, so note it as an integration risk, don't gate on it in the router unit. Tool-call-only mid-stream failures resume as a fresh attempt (documented simplification).
