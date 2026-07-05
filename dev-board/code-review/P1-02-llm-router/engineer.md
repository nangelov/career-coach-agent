# Engineer report — P1-02-llm-router · Revision 1

## Summary
Implemented the multi-LLM failover **router** (`app/llm/router.py`, design §6.6) on top of the
P1-01 `LLMClient` seam. `LLMRouter` wraps an **ordered, config-driven list** of `LLMClient`
instances (primary `zai-org/GLM-5.2` → secondary `Qwen/Qwen3.6-27B`, **no paid last-resort**) and
adds the reliability policy the single-provider client deliberately left out:

- **Per-call timeout** (reuses the client's `timeout=` plumbing) plus a **first-token deadline** for
  streaming — a model that accepts the request but never emits a token fails over.
- **Retry/backoff** for transient `5xx`/`429` on the *same* model (exponential, capped), **distinct**
  from failover to the *next* model. A client `4xx` (non-429) is re-raised without failover (it would
  fail on every model).
- **Redis-backed circuit-breaker** (`CircuitBreaker`): per-model failure counting over a rolling
  window; at threshold the model's circuit "opens" for a cooldown TTL and is skipped; the TTL's
  natural expiry *is* the recovery probe (the next request after cooldown retries it), and a success
  clears all state.
- **Mid-stream failover = resume [DECIDED §6.6]:** content emitted so far is buffered; if a model
  fails after tokens have flowed, the router prefills that partial assistant text as a trailing
  `assistant` message and streams the *continuation* from the next model — the caller sees one
  continuous stream, no restart, no "switching models" notice.

`complete()` / `stream()` mirror the `LLMClient` surface so the router is a drop-in the `agents/`
graph and `api/chat.py` call instead of a raw client.

## Files changed
- `backend/app/llm/router.py` — **new.** `RedisLike` protocol, `CircuitBreaker`, and `LLMRouter`
  (`complete`, `stream`, `from_settings`, `models`, `aclose`).
- `backend/app/llm/errors.py` — added `LLMAllModelsFailedError` (router-terminal failure; carries the
  last per-model `LLMError` as `__cause__`). Additive only — no existing error changed.
- `backend/app/llm/__init__.py` — export `LLMRouter`, `CircuitBreaker`, `RedisLike`,
  `LLMAllModelsFailedError`.
- `backend/app/config.py` — added config-driven router knobs: `LLM_MODELS` (ordered list; overrides
  primary/secondary when set), `LLM_MAX_RETRIES`, `LLM_RETRY_BACKOFF_SECONDS`,
  `LLM_RETRY_BACKOFF_MAX_SECONDS`, `LLM_FIRST_TOKEN_TIMEOUT_SECONDS`, `LLM_CIRCUIT_FAIL_THRESHOLD`,
  `LLM_CIRCUIT_COOLDOWN_SECONDS`, `LLM_CIRCUIT_WINDOW_SECONDS`. All have safe defaults.
- `backend/tests/test_llm_router.py` — **new.** 10 tests over fake `LLMClient` doubles + an in-memory
  fake Redis (no network, no real Redis, no ML stack).

`app/llm/client.py` was **not** modified — its public interface already sufficed (the client's
`timeout=` and its first-party error hierarchy are exactly what the router branches on).

## Key decisions
- **`RedisLike` structural Protocol instead of importing `redis`** — the router carries **no datastore
  dependency**; the real `redis.asyncio.Redis` (from the shared pool in `repositories/redis.py`, §4)
  satisfies the shape, and tests inject a fake. This keeps the circuit-breaker seam clean, keeps the
  CI curated install unchanged (no new dep), and defers pool ownership to `repositories/redis.py`
  where §4 wants it. The router **never constructs its own Redis client** — `from_settings` takes a
  `redis_client` argument. This is the "small repositories-style seam / direct `redis.asyncio` usage
  consistent with P0" the task allowed.
- **Circuit-breaker via two TTL'd keys** (`…:fails` rolling counter, `…:open` cooldown marker). The
  open-marker's TTL expiry doubles as the "periodic recovery probe" (§6.6) — no separate scheduler
  needed on a single ephemeral Space.
- **Error taxonomy drives routing** (built on P1-01's first-party hierarchy):
  - retry same model (transient): `LLMRateLimitError` (429), `LLMResponseError` 5xx.
  - fail over to next model: `LLMTimeoutError`, `LLMConnectionError`, first-token-deadline breach,
    and retry-exhausted transient errors.
  - re-raise immediately (no failover): `LLMResponseError` 4xx (non-429) — a bad request fails on
    every model.
- **Mid-stream resume via assistant-prefill.** On resume the router appends
  `ChatMessage(role="assistant", content=<partial>)` and yields only the next model's *continuation*
  (never re-emitting the prefix), so the caller's stream is seamless. **Caveat/assumption:** this
  relies on the OpenAI-compatible endpoints honoring a trailing partial-assistant message as a
  continuation prefill (standard for these HF chat models). Resume tracks the **content** stream (the
  user-visible tokens, which is what §6.6's "continuing the same response" targets); a failure that
  occurs mid *tool-call* streaming (partial tool call, no content) falls over as a fresh attempt on
  the next model rather than a partial-tool resume — flagging this explicitly as a scoped simplification.
- **First-token deadline** implemented by pulling the first chunk under `asyncio.wait_for`; a breach
  raises `LLMTimeoutError` → failover. Underlying async generators are closed in a `finally`.
- **Injectable `sleep`** (defaults to `asyncio.sleep`) so backoff tests don't actually wait.
- **Config-driven order.** `LLM_MODELS` (env JSON list) re-prioritizes with no code change; empty ⇒
  `[LLM_PRIMARY_MODEL, LLM_SECONDARY_MODEL]`. The list is free/OSS only — there is no paid entry
  anywhere.

## How to verify
From `backend/` (openai + httpx present; router pulls in no ML/redis at import):
```bash
ruff check .
ruff format --check .
mypy app/
pytest -q
```
Results (local `.venv`):
- `ruff check .` → `All checks passed!`
- `ruff format --check .` → `28 files already formatted`
- `mypy app/` → `Success: no issues found in 21 source files`
- `pytest -q` → `15 passed` (5 client + 10 router)

Tests cover every acceptance bullet: primary succeeds (secondary untouched); primary timeout →
secondary serves; primary 429 → 1+2 same-model retries then failover; circuit open in Redis → model
skipped without a call; all circuits open → `LLMAllModelsFailedError`; 4xx not failed over; stream
happy path; **mid-stream failure → secondary resumes with the partial prefill, caller sees
`"Hello world"` continuous**; first-token deadline → failover; breaker trip-and-reset unit.

## Self-check
- [x] Meets acceptance criteria:
  - Router wraps ≥2 `LLMClient` in a configurable order (primary/secondary from settings; `LLM_MODELS`
    override). No paid/last-resort entry anywhere.
  - Per-call timeout enforced; retry/backoff for transient 5xx/429 before failover.
  - Redis-backed circuit-breaker skips an unhealthy model for a cooldown window, then probes (TTL
    expiry) again.
  - Streaming failover resumes on the secondary mid-stream (prefill continuation, no restart / no
    user-facing "switching models" notice).
  - Unit tests pass with mocked clients + fake Redis; **no real Redis needed in CI** and no new CI dep
    (router imports no `redis`).
  - `ruff` + `mypy --strict` clean.
- [x] No secrets committed; token/base-url/model list all from settings (env / Space secrets).
- [x] Layering respected — interface-before-implementation: callers depend on `LLMRouter` +
  `LLMClient` + first-party models; the `redis` client is injected via a `RedisLike` seam, not owned
  here; no agent/graph or `api/chat.py` wiring (P4 / P1-04), no tools (P1-03).
- [x] Tests/lints pass (output pasted above).

## Notes for reviewers
- `client.py` public interface unchanged (task constraint honored). The only cross-file additions are
  additive: one new error class and new settings fields with defaults.
- `CircuitBreaker` + `RedisLike` live in `router.py` (not a new module) to match §8's file structure,
  which lists only `llm/router.py` for this seam.
- The router owns retry/backoff/failover/circuit policy in one place, consistent with P1-01 keeping
  the client at `max_retries=0`.
