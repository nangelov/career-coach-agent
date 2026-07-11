# Architecture review — P4-05-web-searcher · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Worker lives in `agents/` | `app/agents/web_searcher.py` (new); exported from `agents/__init__.py` | None |
| A2 | §3 node list | Web Searcher = search + crawl top hits, return grounded material + citations | `search_and_crawl()` runs search, crawls up to `DEFAULT_CRAWL_PAGES`, maps 1 `Citation`/result, bundles excerpts into `WorkerResult.content` | None |
| A3 | §3 graph shape / LangGraph | Swap the `web_search_node` body only; topology/edges/reducers/node identity unchanged | `graph.py` binds `web_search_node = make_web_search_node()`; `build_graph` adds symmetric `resolved_web_search`; edges/fan-in/`route_after_planner`/reducers untouched; node name preserved | None |
| A4 | DI seam (interfaces-before-impl) | Mirror P4-04 RAG worker: structural `Protocol`, inject collaborators, no second client | `SearchRunner` Protocol (satisfied structurally by `InternetSearchTool`); `search_tool`/`http_client` injected via `build_graph`; reuses the P1-03 tool directly, no second search client | None |
| A5 | §7 / §10 untrusted crawled content | Crawled content is inert data; never executed, never drives tool/worker routing | Fetched text lands only in `content`/`citations`; no tool-call is made *based on* crawled text; `test_crawled_instructions_are_inert_text_only` asserts an injection page stays inert | None |
| A6 | §11 budget posture | free / OSS / self-hosted; no paid path | stdlib `html.parser` extractor — no new dependency; SearXNG (no API key) via existing tool; curated CI install unchanged | None |
| A7 | §4 data ownership / single pool | No rogue store/pool; guest safety | No datastore touched; crawl is stateless HTTP; no user-scoped retrieval (public web ⇒ no access-scoping filter needed, unlike RAG); default node builds the tool lazily *per call*, fails soft when `SEARXNG_URL` unset | None |
| A8 | Fail-soft (worker never raises) | Per-URL + whole-worker degrade cleanly | Per-URL crawl error skipped (`_crawl_page` catch-all → `None`); search error/"not configured" → `WorkerResult(error=...)`, no citations, no raise; tests cover both | None |
| A9 | Bounded resource use | Capped pages / timeout / bytes / text | `DEFAULT_CRAWL_PAGES=3`, `CRAWL_TIMEOUT_SECONDS=8`, `CRAWL_MAX_BYTES=2MB` (streamed, breaks at cap), `EXTRACT_MAX_CHARS=2000`, `text/html` only; sequential (no unbounded fan-out) | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (worker → existing tool via DI seam, no cross-layer leak)
- [x] Honors locked decisions (LangGraph topology intact; no ReAct parser touched; Postgres+Redis only — no new store; no paid path)
- [x] Interfaces-before-implementations (`SearchRunner` Protocol seam, mirrors RAG `SessionProvider`)
- [x] Budget posture respected (stdlib parser, SearXNG, zero new deps)

## Notes
- **§3 scope split (intentional, correctly sequenced — logged follow-up, not a gap).** The §3 Web Searcher
  bullet also says it *"crawls job-profile / role pages to extract structured info (skills, requirements)"*
  and *"Writes findings to Postgres for reuse."* This task deliberately does **neither** — no structured
  role-page schema, no Postgres persistence, no Celery — and its `task.md` constraints explicitly defer that
  full structured-extraction pipeline to **P6**. This is a legitimate foundation-first phase split: P4-05
  ships a general-purpose search+crawl worker for the chat graph; P6 owns the normalized job/role schema +
  Postgres write + async Celery crawl. Flagging so P6 review remembers to close the §3 loop; nothing to
  change here.
- **Inline (non-Celery) crawl is acceptable for the chat turn.** §3/§6 mention Celery for crawling, but that
  is for the heavier P6 role-page pipeline. A small, bounded, synchronous per-turn crawl inside the chat graph
  is the right granularity here and does not pre-couple to P6.
- **Default-node lazy `from_settings()` is fine here** (contrast the §4 no-rogue-DB-pool rule): the search
  tool is a stateless HTTP client with no shared connection pool to protect, it is built per call (not at
  import), and it fails soft when unconfigured — consistent with the blessed P4 worker pattern.
