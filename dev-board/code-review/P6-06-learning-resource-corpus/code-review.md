# Code review — P6-06-learning-resource-corpus · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/ingestion/learning_resources.py:363 | `provider` display value is taken from the untrusted, LLM-extracted page (`provider.strip() or _provider_for_url(url)`) and stored in `meta`. It is pure display data (the allowlisted URL host is authoritative for identity/`source_key`), so low risk — but a page could set a misleading provider label. | Optional: prefer `_provider_for_url(url)` (the allowlist name) as the authoritative provider and treat the extracted value as a fallback only. Not gating. |
| C2 | nit | app/ingestion/learning_resources.py:340-343 | A URL that fails to fetch/extract is not recorded in `into`, so if the same URL resurfaces under another skill it is re-crawled (robots+rate-limit re-paid). Minor inefficiency, bounded by `max_results_per_skill`. | Optional: cache failed URLs to skip re-crawl. Not gating. |
| C3 | nit | app/ingestion/crawl.py:27-30 | DRY: `fetch_page_text`/`robots` helpers duplicate the equivalent private copies in `market_agent.py`. | Engineer already documented this as a deliberate, task-scoped deferral (the "do not modify market_agent" constraint) with a follow-up note. Architecture-lane; noted only. |

## Notes
- **Security — strong.** Every fetch runs through the SSRF-guarded `build_guarded_client` (page + robots share the guarded client and the same per-host `HostRateLimiter`). The provider allowlist (`PROVIDER_HOSTS`, exact-host / `.suffix` match — no `notcoursera.org`/`coursera.org.evil.com` bypass) bounds crawl targets, `_normalize_provider_url` drops userinfo/query/fragment, and the production default resolver blocks private IPs. LinkedIn Learning correctly excluded (ToS).
- **robots.txt line-collapse pitfall (my recurring check): handled correctly.** `fetch_robots_body` returns the body verbatim (no whitespace-collapse / HTML-strip) while `fetch_page_text` collapses only page text — `test_robots_body_preserves_line_structure` + `test_real_robots_checker_over_guarded_fetch_enforces_disallow` prove a real `Disallow` is honored end-to-end, not just via a fake checker.
- **Untrusted content:** page fenced via `fence_untrusted` before the LLM call; normalization is a forced tool-call (`tool_choice` pins `record_learning_resource`), no free-text parsing. Test asserts both the fence markers and forced tool_choice. Tool-arg parser (`_parse_resource`) is fully guarded — non-dict args, non-list skills, non-str items, bad JSON all fail soft to `None`/`[]` (no raise out of the fail-soft node).
- **Persistence / idempotency:** delete-before-insert keyed on the normalized-URL `source` (`user_id IS NULL`, `source_type='curated'`, distinct `learning_resource:` prefix — no cross-corpus collision); chunks cascade; embedding computed outside the txn. Same-URL-across-skills dedupes to one doc with unioned skills. Signatures verified against `add_kb_chunk`, `KbDocument`, `fence_untrusted`, `chunk_text`, `SearchRunner`, `LLMCompleter`, and the Tavily `{title,url,snippet}` result shape — all line up.
- **Off request path:** Celery-only (`tasks.mine_learning_resources`, registered in `celery_app.include`); test asserts registration; no api/service caller.
- Verified locally: `ruff check` clean on all new files; `pytest tests/test_learning_resources.py tests/test_crawl.py` → 21 passed. Acceptance criteria all met.
