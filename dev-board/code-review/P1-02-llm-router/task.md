# Task P1-02-llm-router — LLM failover router
- **Phase:** P1   **Status:** ENG   **Tags:** (B)

## Scope
Implement `backend/app/llm/router.py` per design §6.6, building on top of the `LLMClient` interface and
`HFOpenAICompatibleClient` delivered in `P1-01-llm-client` (see
`dev-board/code-review/P1-01-llm-client/engineer.md` for the exact seam: one `LLMClient` instance = one
model id, first-party `LLMError` hierarchy in `app/llm/errors.py`, `max_retries=0` on the client so retry
policy belongs entirely here).

Build a `LLMRouter` (name it however fits, but expose it as the thing `agents/`/`api/chat.py` call instead of
a raw client) that:
- Holds an **ordered list** of `LLMClient` instances / model configs: primary `zai-org/GLM-5.2` → secondary
  `Qwen/Qwen3.6-27B`, **no paid last-resort** — config-driven (model list + order via env/settings, no code
  change to re-prioritize).
- **Per-call timeout** (reuse the client's timeout plumbing from P1-01; add a first-token deadline concept for
  streaming if not already covered).
- **Retry/backoff** for transient 5xx/429 (`LLMRateLimitError`, `LLMResponseError` with 5xx) — distinct from
  failover to the next model.
- **Redis-backed circuit-breaker**: track health per model (recent errors/timeouts) and temporarily skip an
  unhealthy endpoint; periodic recovery probes to bring it back in rotation. Add a small
  `repositories`-style seam or direct `redis.asyncio` usage consistent with how P0 wired Redis (check
  `app/config.py` / `docker-compose.yml` for the Redis connection settings already in place).
- **Mid-stream failover = resume [DECIDED]:** if the primary fails *after* tokens have already streamed, the
  in-flight response **resumes on the secondary model** continuing the same response — not a restart with a
  "switching models" notice. Implement this for the `stream()` path (buffer/replay just enough context to hand
  off cleanly; document the approach in `engineer.md`).
- Non-streaming `complete()` failover is simpler: on failure before any output, just try the next model in
  order.
- Unit tests (mocked clients — reuse the same `httpx.MockTransport` pattern from P1-01's
  `test_llm_client.py`, or fake `LLMClient` doubles) covering: primary succeeds; primary times out → secondary
  serves; primary 429 → backoff-retry then failover; circuit breaker skips a model marked unhealthy in Redis;
  mid-stream failure on primary → secondary resumes and the caller sees one continuous stream.

## Acceptance criteria
- [ ] Router wraps ≥2 `LLMClient` instances in a configurable order (primary/secondary from settings).
- [ ] Per-call timeout enforced; retry/backoff applied for transient 5xx/429 before failing over.
- [ ] Redis-backed circuit-breaker: an unhealthy model is skipped for a cooldown window, then probed again.
- [ ] Streaming failover resumes on the secondary mid-stream (no restart/no user-facing "switching models"
      notice) when the primary fails after tokens have already been emitted.
- [ ] No paid/last-resort provider anywhere in the model list.
- [ ] Unit tests pass with mocked clients/Redis (fakeredis or a mocked redis client — no real Redis needed in
      CI unless already available per P0 CI setup; check `.github/workflows/backend-ci.yml`).
- [ ] `ruff` + `mypy` clean.

## Design references
- dev-board/plan.md: P1 — Walking skeleton
- dev-board/app-design-and-features.md: §6 item 7 (failover order, no paid last-resort), §6.6 (LLM failover
  router — full spec: timeout, circuit-breaker, retry/backoff, mid-stream resume, config-driven), §8 Target
  Project Structure (`backend/app/llm/router.py`)
- dev-board/code-review/P1-01-llm-client/engineer.md — the `LLMClient` interface/types/errors this task builds on

## Constraints / non-goals
- Do not modify `app/llm/client.py`'s public interface unless something is genuinely missing for the router to
  function — if so, keep the change minimal and call it out explicitly in `engineer.md`.
- No agent/graph wiring here (that's P4) and no `api/chat.py` endpoint here (that's P1-04) — this task is the
  router unit only, though a short "how a caller would use this" example in the report is welcome.
- No tool implementations here (P1-03).
