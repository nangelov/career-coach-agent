# Code review — P1-01-llm-client · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/llm/client.py:177 | `from_settings(config: Settings = settings)` binds the module-level singleton as a default at def-time. It works (singleton, never mutated), but a mutable/object default is easy to misread and couples the classmethod to import order. | Optional: default to `None` and resolve `config or settings` inside the body. Non-blocking. |
| C2 | nit | backend/app/llm/client.py:374-376 | `_translate_error` has two trailing branches (`isinstance(exc, OpenAIError)` and the final fallthrough) that both `return LLMError(str(exc))` — functionally identical, so the `OpenAIError` check is dead. | Collapse to a single catch-all, or make the `OpenAIError` branch distinct if intended. Non-blocking. |
| C3 | nit | backend/app/llm/client.py:278,286 | `_to_tool_params` / `_to_tool_choice_param` return `... | Any` to accommodate the `omit` sentinel, which collapses the annotation to `Any` and loses the typed part. | Acceptable given the SDK's `Omit` typing; could annotate with `| Omit` for precision. Non-blocking. |

## Notes
- **Verified locally** (openai 2.44.0, `uv run --no-sync`): `pytest tests/test_llm_client.py` → 4 passed; `ruff check` → all passed; `ruff format --check` → clean; `mypy app/` → success, 20 files. No network calls (tests use `httpx.MockTransport`; `conftest.py` seeds dummy secrets via `setdefault`).
- **Acceptance criteria all met:** `LLMClient` ABC + concrete `HFOpenAICompatibleClient`; callers depend on the interface and first-party `types.py`/`errors.py` (the `openai` SDK is confined to `client.py`). Native tool-calling round-trips structurally (schema in → parsed `tool_calls` out) with **no regex/ReAct text parsing** anywhere. Streaming is a genuine async generator yielding content + tool-call deltas. Config (base URL / token / model / timeout) flows from `app/config.py`; no hardcoded secrets, no `.env` committed.
- **Correctness:** async-generator `stream()` correctly defers the `create()` call to first `__anext__`; both open-time and mid-stream SDK errors are translated to the first-party hierarchy (`except LLMError: raise` guards against double-wrapping). Error-translation ordering is correct against the openai SDK class hierarchy (`APITimeoutError ⊂ APIConnectionError`, `RateLimitError ⊂ APIStatusError` — most-specific checked first). Empty-`choices` chunks are tolerated; empty `tools` list correctly maps to `omit`.
- **Security:** token/base-url sourced from settings only; nothing logged; no `run_python_code`/eval/arbitrary execution; tool *arguments* are kept as an unparsed raw JSON string (client never `json.loads` untrusted model output), which is the right seam.
- **Scope discipline honored:** no failover/retry/circuit-breaker here (`max_retries=0`), correctly deferred to P1-02's router; no tool implementations.
- The three nits above are stylistic and can be deferred; none blocks merge.
