# Engineer report — P4-05-web-searcher · Revision 1

## Summary
Replaced the stub `web_search_node` with a real **Web Searcher + Crawler** worker
(`app/agents/web_searcher.py`), mirroring the P4-04 RAG worker's shape (DI seam, fail-soft,
`WorkerResult`/`Citation` mapping). The worker runs the existing P1-03 `InternetSearchTool`
(SearXNG, no API key) directly, then **crawls** a small capped set of the top result URLs to
extract more grounded text than a snippet gives, and returns one citation per result plus a
numbered content bundle for the responder. Crawled page text is treated strictly as **inert
data** — it only lands in `content`/`citations` text fields; nothing executes it or lets it
drive tool/worker routing (design §7/§10). `graph.py`'s `web_search_node` now calls the real
node; topology/edges/reducers are unchanged.

HTML→text extraction uses the **stdlib `html.parser`** (no new dependency) — chosen over
beautifulsoup4/selectolax so the curated CI install stays unchanged and the budget/OSS posture
(§11) holds.

## Files changed
- `app/agents/web_searcher.py` (new) — `search_and_crawl()` (search → bounded crawl → map),
  `make_web_search_node()` factory (P4-04 pattern), `SearchRunner` Protocol seam, stdlib
  `_TextExtractor(HTMLParser)`, and bounded-crawl helpers.
- `app/agents/graph.py` — import + module-level `web_search_node = make_web_search_node()`;
  `build_graph()` gains `search_tool` / `http_client` injection params and a
  `resolved_web_search` node (symmetric with `resolved_rag`); docstrings updated; the old
  `def web_search_node` stub removed (job/pdp stubs keep the shared `_worker_update`).
- `app/agents/__init__.py` — export `make_web_search_node`, `search_and_crawl`.
- `tests/fakes.py` — `FakeSearchTool` (structural `SearchRunner`), `web_result()`,
  `fake_crawl_client()` (httpx `MockTransport`) — shared by the new + graph tests.
- `tests/test_web_searcher.py` (new) — unit + real-graph integration coverage.
- `tests/test_agent_graph.py` — the two fan-in tests that relied on the web stub's canned
  citation/content now inject the fake search tool + mock crawl transport (see Tests note).

## Key decisions
- **Call the search tool directly, not via the LLM tool-loop** — the worker knows the query
  from `AgentState`, same posture `rag_agent` uses calling `hybrid_search` directly (task
  "reuse, don't reinvent"). No second search client.
- **`SearchRunner` Protocol seam** mirrors `rag_agent.SessionProvider`: the worker depends on a
  *capability* (`async run(args) -> ToolResult`) that `InternetSearchTool` satisfies
  structurally, so `build_graph` wires the real tool in prod and tests inject a fake without a
  cast/subclass.
- **Bounded on every axis** (acceptance #3): `DEFAULT_CRAWL_PAGES=3` pages, `CRAWL_TIMEOUT=8s`,
  `CRAWL_MAX_BYTES=2MB` streamed (via `aiter_bytes`, breaks at the cap — no unbounded memory),
  `EXTRACT_MAX_CHARS=2000` per page; only `text/html` bodies read.
- **Two-level fail-soft** (acceptance #5): per-URL crawl errors are caught → the page is
  skipped but the result is still cited; a whole-worker search failure ("not configured" /
  error `ToolResult`) → `WorkerResult(error=...)` with no citations, never raises.
- **Crawled text is inert** (acceptance #4, design §7/§10): fetched text flows only into
  `content`/`citations`; the worker calls no tool *based on* crawled text, so it is not an
  injection vector. A dedicated test asserts an "IGNORE ALL INSTRUCTIONS…" page is captured as
  plain text and does not change behavior. Full classifier is P10 (out of scope).
- **Import-time default stays side-effect-free**: module-level `web_search_node` builds the
  settings-configured tool lazily *per call* and fails soft when `SEARXNG_URL` is unset — same
  posture as the default `rag_node` without a DB provider.

## How to verify
- `uv run --no-sync ruff check .` · `uv run --no-sync mypy app/`
- `uv run --no-sync python -m pytest tests/test_web_searcher.py tests/test_agent_graph.py -q`
- Full suite: `uv run --no-sync python -m pytest -q`

## Tests (final step — mandatory)
- `ruff check .` → **All checks passed!**
- `ruff format --check` on changed files → **5 files already formatted** (my files). NOTE:
  a repo-wide `ruff format --check .` flags 5 *pre-existing* files I did not touch
  (`app/repositories/models/identity.py`, `tests/test_agent_planner.py`,
  `tests/test_feedback_reader.py`, `tests/test_p3_exit_verification.py` — untracked/committed
  by other tasks); left as-is (out of scope).
- `mypy app/` → **Success: no issues found in 67 source files**.
- `pytest -q` → **274 passed, 43 skipped** (skips are the pre-existing heavy-ML/DB-gated ones;
  all my new tests ran).
- **Test change, not a weakening:** `test_parallel_workers_fan_in_without_clobbering` and
  `test_responder_merges_all_worker_outputs` previously asserted the *stub's* canned
  `web_search` citation/content (e.g. the literal string `"web_search"` in the response). The
  stub is gone, so those assertions were stale. Fixed by injecting a fake search tool + mock
  crawl transport so the real worker contributes a real citation/content, and asserting on the
  real merged content (`"WebFinding"`) instead of the stub marker. No real network in any test.

## Self-check
- [x] Meets acceptance criteria (real search+bounded crawl, citations, bounded, inert data,
      two-level fail-soft, unit + real-graph integration test, ruff/mypy clean, suite green)
- [x] No secrets committed; layering respected (worker calls the existing tool/DI seam, no new
      driver/client)
- [x] Graph topology/edges/reducers unchanged; node name/identity (`web_search_node`) preserved
- [x] No new dependency added (stdlib `html.parser`); curated CI install unchanged
- [x] Tests/lints pass (output pasted above)
