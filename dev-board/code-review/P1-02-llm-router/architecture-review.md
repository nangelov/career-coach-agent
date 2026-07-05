# Architecture review — P1-02-llm-router · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Failover router at `backend/app/llm/router.py`; §8 lists only `client/router/embeddings` under `llm/` | `router.py` new; `CircuitBreaker` + `RedisLike` kept **in** `router.py` (no extra module), one new error class in `errors.py`, exports in `__init__.py` | None. Placement matches §8; keeping the breaker in-module is the right call for the single-file node. |
| A2 | Interface-before-impl (llm seam) | Router composes `LLMClient` instances, branches on **first-party** error types, no `openai` re-import ([[project-llm-layer-seam]]) | Router imports only `.client` (`LLMClient`/`HFOpenAICompatibleClient`/`ToolSchema`), `.errors`, `.types`; retry/failover keyed on `LLMRateLimitError`/`LLMResponseError.status_code`/`LLMTimeoutError` | None. The blessed P1-01 seam contract is honored exactly. |
| A3 | Failover policy lives only in router (P1-01 ruling) | `client.py` stays `max_retries=0`, single-model; retry/backoff/failover/circuit/resume only in `router.py` | `client.py` public interface **unmodified** (confirmed); all reliability policy is in `router.py` | None. |
| A4 | §6.6 failover order + no paid last-resort; locked #4 | primary `zai-org/GLM-5.2` → secondary `Qwen/Qwen3.6-27B`, free OSS only | `from_settings` builds `LLM_MODELS or [PRIMARY, SECONDARY]`; config defaults correct; no paid entry anywhere | None. |
| A5 | §6.6 config-driven order/timeouts | model list + order + timeouts via env, no code change to re-prioritize | `LLM_MODELS`, `LLM_MAX_RETRIES`, `LLM_RETRY_BACKOFF_*`, `LLM_FIRST_TOKEN_TIMEOUT_SECONDS`, `LLM_CIRCUIT_*` added to `config.py` with safe defaults | None. |
| A6 | §6.6 Redis circuit-breaker + recovery probes; locked #9 (Redis only) | health-track per model in Redis, skip unhealthy, periodic recovery probes | `CircuitBreaker` via two TTL'd keys (`:fails` rolling counter, `:open` cooldown); open-marker TTL expiry *is* the probe; Redis injected via `RedisLike` Protocol, never self-constructed (defers pool to `repositories/redis.py`, §4) | None. TTL-expiry-as-probe is an acceptable reading of "periodic recovery probes" on a single ephemeral Space. |
| A7 | §6.6 + locked #7 mid-stream = **resume** (NOT restart-with-notice) | on post-first-token failure, resume on next model continuing the same response, no "switching models" notice | `stream()` buffers `accumulated` content, prefills a trailing `assistant` message, yields only the continuation; no notice emitted | None. The most failure-prone locked decision is implemented correctly. |
| A8 | §6.6 per-call + first-token timeout | per-call timeout, optional first-token deadline for streaming | `_per_call_timeout` threaded into `complete/stream`; `_first_chunk` pulls first chunk under `asyncio.wait_for` → `LLMTimeoutError` → failover | None. |
| A9 | §11 budget posture | free/OSS/self-hosted; no paid | model list free OSS only; reuses existing Redis; no new dependency (`RedisLike` avoids importing `redis`) | None. |
| A10 | Phase fit / non-goals | router unit only — no agent/graph (P4), no `api/chat.py` (P1-04), no tools (P1-03) | `complete`/`stream` mirror the client surface as the drop-in callers will use; no wiring beyond the llm layer | None. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — router lives in `llm/`, depends only on the `LLMClient` interface + first-party types/errors; Redis reached through an injected `RedisLike` seam, not a DB driver owned here.
- [x] Honors locked decisions — native tool-calling pass-through (no ReAct parser); Postgres+Redis only (circuit state in Redis, no new store); mid-stream **resume** not restart ([[project-v2-locked-stack]] #7); free-OSS failover, no paid last-resort (#4).
- [x] Interfaces-before-implementations — composes `LLMClient`; circuit-breaker seam via `RedisLike` Protocol so the real `redis.asyncio.Redis` and a test fake both satisfy it.
- [x] Budget posture respected (free/OSS/self-hosted; no new dependency).

## Notes
- **Scoped simplification (accept, follow-up):** mid-stream resume tracks the **content** stream; a failure that occurs mid *tool-call* streaming (partial tool call, no content emitted) fails over as a fresh attempt rather than a partial-tool resume. §6.6's resume decision targets "continuing the same response" (user-visible tokens), so this is within the letter of the locked decision. Flag for P4 (agent/graph) to confirm tool-call streams are re-driven safely on failover; no change required here.
- **Design assumption (accept):** resume relies on the OpenAI-compatible HF endpoints honoring a trailing partial-`assistant` message as a continuation prefill. This is the standard technique for these chat models and matches "continuing the same response." Worth an integration check when P1 is exercised end-to-end; not a gate.
- **Carried follow-up from P1-01 (not this task's scope):** `LLM_BASE_URL` default is still the legacy serverless `https://api-inference.huggingface.co/v1`; HF Inference Providers' OpenAI-compatible surface is `https://router.huggingface.co/v1`. The router's clients inherit this via `from_settings`. Config-driven, so a Note not a gate — confirm the correct default before P1 runs live ([[project-llm-layer-seam]]).
- **Doc nit (non-blocking):** `LLM_CIRCUIT_FAIL_THRESHOLD`'s description says "Consecutive-window failures" but the counter trips on N failures *within* the rolling window (not strictly consecutive). Cosmetic wording only.
