# Architecture review — P1-01-llm-client · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | `LLMClient` interface + HF/OpenAI-compatible impl at `backend/app/llm/client.py` | `client.py` holds `LLMClient` ABC + `HFOpenAICompatibleClient`; supporting `types.py` / `errors.py` added under `llm/` | None. §8 is not exhaustive; splitting first-party message/result types and the error hierarchy out of `client.py` is sound decomposition, not a structure deviation. |
| A2 | Interface-before-implementation (§2, plan.md) | Model behind a swappable `LLMClient` interface; callers depend on the interface, not the SDK | `LLMClient` ABC (`model`, `complete`, `stream`); `openai` SDK import confined to `client.py`; agents/router speak first-party `types.py`/`errors.py` | None. Clean seam; SDK is a confined implementation detail. |
| A3 | Native tool-calling, ReAct parser deleted (§6 item 6, locked #2) | `tools=[...]` in → `tool_calls` out; **no** text/ReAct parsing | Uses OpenAI-compatible `tools`/`tool_choice`/`tool_calls`; no regex/`output_parser.py` equivalent anywhere; streaming carries `ToolCallDelta` fragments | None. Locked decision honored. |
| A4 | §6.6 router is the unit the failover router wraps | Single-provider client = the clean unit an ordered model list wraps; failover/retry/circuit-breaker NOT here | One client = one model id; `max_retries=0` default; first-party error hierarchy (`LLMTimeoutError`/`LLMRateLimitError`/`LLMResponseError` w/ `status_code`) maps to §6.6 failover-vs-retry triggers; no failover logic present | None. Correctly leaves failover/resume to P1-02; error taxonomy is exactly the seam §6.6 needs. |
| A5 | Config-driven, no hardcoded secrets (§8 config.py, §11) | Base URL / token / model id / timeout from `config.py`; secrets from env / Space secrets | `from_settings()` pulls `LLM_PRIMARY_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`, `HF_API_TOKEN`; no literals in `client.py` | None. Config posture correct. |
| A6 | Budget posture (§11, locked) | Free/OSS/self-hosted; no paid provider | `openai` SDK pointed at HF Inference (free OSS); GLM-5.2 primary default; no paid last-resort introduced | None. |
| A7 | Phase fit (P1 walking skeleton) | Single-provider client only; no premature coupling to router (P1-02) or tools (P1-03) | Failover, tool impls, embeddings all explicitly deferred; `stream()` surfaces mid-stream errors so the router can later *resume* (locked #7) without this module owning it | None. Foundation-first sequencing respected. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — `llm/` is a leaf infra layer; no cross-layer leak (SDK confined to `client.py`).
- [x] Honors locked decisions — no ReAct parser (#2); native tool-calling; no paid fallback (#4); no premature failover/resume (#7). Postgres/Redis/SSO/embeddings N/A to this task.
- [x] Interfaces-before-implementations — `LLMClient` ABC is a real swap seam; first-party `types`/`errors` decouple callers from `openai`.
- [x] Budget posture respected (free/OSS/self-hosted).

## Notes
- **N1 (minor, config default — cheap to change, not a gate):** `LLM_BASE_URL` defaults to `https://api-inference.huggingface.co/v1` (the legacy serverless Inference API). HF **Inference Providers** — the OpenAI-compatible surface §2/§6 actually calls for, and the one that brokers GLM-5.2 native tool-calling across providers — is served from `https://router.huggingface.co/v1`. The value is config-driven and overridable via env, so this does not block P1-01, but the *default* should be corrected before P1's walking skeleton is exercised end-to-end (P1-02+), or native tool-calling may not resolve against the intended endpoint. Flagging for the engineer/orchestrator to confirm the deployment base URL; folded into `config.py` (P0 surface), not `client.py`.
- **N2 (follow-up for P1-02):** The error hierarchy deliberately exposes `status_code` and separates timeout/connection/rate-limit/response — the router (P1-02) should branch on these first-party types (not re-import `openai`). This is the intended contract; recorded so P1-02 review can hold the router to it.
- **N3:** `openai>=2.0` floor bump (for the `omit` sentinel) is a dependency/correctness detail — deferred to the code-reviewer; no design impact.
