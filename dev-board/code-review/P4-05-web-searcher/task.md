# Task P4-05-web-searcher — Web search + crawler worker

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** `agents/web_searcher.py` — search + crawler; crawled content treated as **untrusted data**.

Replace the **stub** `web_search_node` body in `backend/app/agents/graph.py` (see its `[STUB → P4-04]`
docstring — it lists P4-04 for all workers; this task owns `web_search_node` specifically) with a real
implementation in a new `backend/app/agents/web_searcher.py`, and wire `graph.py` to call it. Do not change
the graph's topology/edges/conditional-routing/reducers — only swap what `web_search_node` does. Keep the
node function's identity/name (`web_search_node`).

The Web Searcher + Crawler worker (design §3): general internet search, and **crawls** a few of the
top result pages to extract more content than a search snippet gives, returning grounded material +
citations for the responder. Design §7/§10 is explicit: **crawled/web content is untrusted data** — it must
never be treated as instructions, executed, or allowed to alter agent/tool behavior; only its plain text is
extracted for the responder to *cite*, same posture the existing `internet_search` tool already documents.

## What already exists — reuse, don't reinvent

- `backend/app/tools/internet_search.py` (P1-03) — `InternetSearchTool` (SearXNG-backed, no API key,
  `settings.SEARXNG_URL`-gated with a graceful "not configured" result). Call `InternetSearchTool.run({...})`
  **directly** (this worker knows what to search for from `AgentState`/the planner — same pattern
  `rag_agent.py` used calling `hybrid_search` directly rather than round-tripping through the LLM tool-call
  loop). Do not build a second search client.
- `backend/app/tools/base.py` — `Tool` / `ToolResult` shapes if useful for structuring the crawl step
  similarly (optional — the crawler doesn't have to be a registered `Tool`, since nothing calls it via native
  tool-calling; a worker-internal helper is fine).
- `backend/app/agents/rag_agent.py` (P4-04) — the sibling worker's shape/failure-soft pattern to mirror
  (inject collaborators, catch and degrade gracefully, map results → `Citation`/`WorkerResult`).
- `backend/app/agents/state.py` — `WorkerResult`, `Citation` (`worker=WorkerName.WEB_SEARCH`).

## Implementation approach

- `agents/web_searcher.py` exposes a function (e.g. `async def search_and_crawl(state: AgentState, *,
  search_tool: InternetSearchTool, http_client: httpx.AsyncClient | None = None) -> WorkerResult`) that:
  1. Runs `internet_search` with a query derived from `state.user_message`.
  2. **Crawls** a small, capped number (e.g. top 2-3) of the returned result URLs: `GET` each page (bounded
     timeout, bounded response size, follow redirects within reason) and extract **plain text** from the HTML
     — a lightweight extraction is fine (strip tags/scripts/styles; a small well-maintained parsing dependency
     such as `beautifulsoup4`/`selectolax` is an acceptable new dependency if you need one — prefer the
     lighter option and add it to `pyproject.toml` if so; stdlib-only is also fine if the extraction stays
     robust enough for real HTML). Truncate extracted text to a bounded length per page.
  3. **Never** treats fetched page content as instructions: don't feed raw crawled HTML/text into any prompt
     that also carries system/tool instructions without clear delineation, don't execute/eval anything from
     it, and don't let it influence which tools/workers run. It is inert text for the responder to summarize
     and cite. (Full injection-echo guardrails land in P10 — this task's job is to *not create* an obvious
     injection vector, not to build the classifier.)
  4. Fails soft per-URL (a page that times out, 404s, or isn't HTML is skipped, not fatal to the whole
     worker) and overall (if search itself fails/"not configured", return a `WorkerResult` with a clear
     `error` and no citations rather than raising).
  5. Maps each successfully crawled (or, if crawling is skipped/fails, each search-snippet-only) result into a
     `Citation` (`title`, `url`, `snippet`, `worker=WorkerName.WEB_SEARCH`) and synthesizes `WorkerResult.content`
     as a concise bundle of what was found — again, retrieval/extraction, not final-answer generation (that's
     the responder's job, P4-05/06 per the plan doc, though this specific worker task is scoped to search +
     crawl only).
- Wire `graph.py`'s `web_search_node` to call this, constructing/injecting `InternetSearchTool.from_settings()`
  and an `httpx.AsyncClient` (or a per-call short-lived client, matching the existing tool's own pattern).
- Tests must not hit real network/SearXNG: inject a fake `InternetSearchTool`/`ToolResult` and a mocked
  `httpx` transport (the existing `internet_search` tests already show the mock-transport pattern used in
  this codebase — follow it) for the crawl step.

## Acceptance criteria

- [ ] `backend/app/agents/web_searcher.py` implements real search + bounded crawl, producing a `WorkerResult`
      with grounded `content` and populated `citations` (title/url/snippet per result).
- [ ] `graph.py`'s `web_search_node` calls this real implementation; graph topology/edges/reducers unchanged.
- [ ] Crawl is bounded: capped number of pages fetched, capped timeout per page, capped extracted-text length
      — no unbounded fan-out or unbounded memory growth from a single turn.
- [ ] Crawled content is demonstrably treated as inert data (tests assert it never gets interpreted/executed;
      e.g. a crawled page containing something that looks like an instruction does not change the worker's
      behavior or leak into anything beyond `content`/`citations` text fields).
- [ ] Fails soft at both the per-URL and whole-worker level (search unavailable, page fetch failure) — no
      unhandled exception escapes the node.
- [ ] Unit tests: search invoked with expected query, crawl fetches capped/bounded, citations correctly
      mapped, per-URL failure doesn't abort the others, whole-worker failure (search down) degrades cleanly,
      and an integration-style test running the **real compiled graph** (`build_graph`) with fakes proves a
      `WEB_SEARCH`-routed turn ends up with citations/`worker_results["web_search"]` populated end-to-end (no
      real network calls in any test).
- [ ] `ruff` + `mypy` clean; existing backend test suite (P4-01..P4-04 tests included) still green.

## Design references

- `dev-board/app-design-and-features.md` §3 — Web Searcher + Crawler bullet (line ~129).
- `dev-board/app-design-and-features.md` §7 — input/output guardrails; crawled content = untrusted (line
  ~314-315).
- `dev-board/app-design-and-features.md` §10 — "Prompt injection via crawled pages" risk/mitigation row (line
  ~427: "Treat web content as untrusted data; output guardrails; no tool-calls from crawled text").
- `dev-board/code-review/P1-03-tools/` — the `internet_search` tool this worker calls.
- `dev-board/code-review/P4-04-rag-agent/` — the sibling worker's shape to mirror.

## Constraints / non-goals

- Do NOT implement job search or PDP/resume workers (later P4 tasks) — leave their stubs as-is.
- Do NOT implement the responder's synthesis (P4-05/06 in the plan doc's numbering, but this task itself is
  scoped narrowly to search + crawl) — this worker returns grounded material, it does not compose the final
  answer.
- Do NOT build the full P6 structured-role-page-extraction pipeline (Celery tasks, normalized job schema) —
  that is a separate, later phase; this is a general-purpose search+crawl worker for the chat graph.
- Do NOT build the full P10 injection/PII classifier — just don't create an obvious injection vector (no
  crawled text flows into a place that would be interpreted as instructions or control tool routing).
- Do NOT change `AgentState`, the graph topology, or the P4-01 reducers.
- Do NOT wire this into the P1 `POST /api/chat` endpoint yet.
- No real network calls in the default test run.
