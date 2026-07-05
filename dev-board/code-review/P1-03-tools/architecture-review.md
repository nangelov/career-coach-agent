# Architecture review — P1-03-tools · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Native tools live in `backend/app/tools/` ("native tool-call definitions (schemas + impls)", §8 line 362) | `tools/{base,current_date_and_time,internet_search,registry,__init__}.py` — schemas + impls exactly there | none |
| A2 | Locked #2 — native tool-calling, no ReAct parser | Tools speak the OpenAI `tools[]` schema + native `ToolCall`/`FunctionCall` vocabulary; no text-parsing seam | Schemas are `{"type":"function","function":{...}}` dicts; `ToolRegistry.execute(ToolCall)->ChatMessage` round-trips via first-party `app.llm.types`; no output-parser reintroduced | none |
| A3 | Interfaces-before-implementations | A real seam so tool #3 is "drop a module + register" | `Tool` ABC (name/schema/async run) + `ToolRegistry` + single `build_default_registry()` wiring point | none |
| A4 | §11 budget posture — free/OSS/self-hosted | `internet_search` on a free/OSS backend, no paid key | SearXNG (OSS, self-hostable, no API key), URL from `settings.SEARXNG_URL`, inert-when-unset; no hard-coded secret | none |
| A5 | §11 job-search separation | SerpAPI/Google-Jobs is a *separate* P6 concern, not this general web tool | `internet_search` is distinct from SerpAPI; schema even instructs the model not to use it for job listings; `SERPAPI_API_KEY` left untouched for P6 | none |
| A6 | §5 untrusted external data | Crawled/searched web content treated as untrusted, never executed as instructions (§5 line 314) | Results reduced to plain `{title,url,snippet}` strings, snippet-truncated (400 ch), count-clamped [1,10]; returned as JSON string, not interpreted | none |
| A7 | Layering (Router→Service→Agent/Repo) | Tools are an agent-facing seam; no DB drivers, no cross-layer leak | `tools/` imports only `app.llm.types` + `app.config` + `httpx`; no repository/DB access; no provider SDK import (local `ToolSchema` alias avoids transitive `openai`) | none |
| A8 | P1-01 seam contract ([[project-llm-layer-seam]]) | Consume the first-party `ChatMessage`/`ToolCall`/`FunctionCall` vocabulary unchanged; no `llm/` edits | `role="tool"` message built via `ToolResult.to_message(tool_call_id, name)`; `ChatMessage.to_openai` already emits `tool_call_id`/`name`; zero changes to `llm/*` | none |
| A9 | Phase fit (P1 foundation) | Deliver the tools + a documented one-round-trip example; no `/api/chat` loop (P1-04), no job/RAG tools | Tools + registry only; round-trip example in `engineer.md`; no endpoint, no SerpAPI, no pgvector coupling | none |

## Cross-cutting checks
- [x] Fits target structure (§8 `tools/`) + layering (agent-facing seam, no DB/service-layer leak)
- [x] Honors locked decisions (native tool-calling / no ReAct parser; no Postgres/Redis touched improperly; free/OSS backend; §11 SerpAPI kept separate for P6)
- [x] Interfaces-before-implementations (`Tool` ABC + `ToolRegistry` are the swap seam)
- [x] Budget posture respected (SearXNG OSS/self-hosted, no API key, no paid last-resort)

## Notes
- **Follow-up (cheap, not a gate):** `ToolSchema` is defined twice — `tools/base.py` and `llm/client.py` — as structurally identical `dict[str, Any]` aliases. The engineer's rationale (keep `tools/` free of a transitive `openai` import) is sound and the two are trivially reconcilable later (e.g. a shared `schemas/`-level alias) if the duplication ever drifts. Logged, no change required now.
- **Not this task's concern:** the `LLM_BASE_URL` legacy-serverless default flagged in [[project-llm-layer-seam]] is a P1-01 follow-up; `internet_search` does not touch the LLM endpoint, so it is unaffected here.
- Config additions (`SEARXNG_URL` default `""`, `SEARCH_TIMEOUT_SECONDS` default `10.0`) are sourced from `app/config.py` with no secrets committed — consistent with the §11 self-hosted, config-driven posture. The "inert until an operator points `SEARXNG_URL` at an instance" default is the right budget/deploy posture for P1.
