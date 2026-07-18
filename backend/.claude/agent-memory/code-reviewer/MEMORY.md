# Code-reviewer memory index

- [Chat/LLM layer review checks](project-chat-llm-review-checks.md) — recurring things to verify in P1 chat/LLM/tool code (SSE injection, client-supplied history trust, lazy-DI races, native-tool-only)
- [Tool-arg parsing guards](project-tool-arg-parsing-guards.md) — half-guarded tool-call JSON parsers raise out of fail-soft nodes and 500 the turn; check every field's type guard
- [Crawler/fetcher SSRF](project-crawler-fetcher-ssrf.md) — server-side fetch of URLs from untrusted data (crawler, P6 extractors) is an SSRF surface; check scheme/IP allowlist + redirects, co-located Redis/Postgres raise the stakes
- [Frontend untrusted URL in href](project-frontend-untrusted-url-href.md) — citation/source URLs from web-search/crawl rendered into `<a href>` are a javascript:-scheme DOM-XSS sink; React doesn't sanitize, no CSP — require http/https scheme check
- [Upload endpoint size guard](project-upload-endpoint-size-guard.md) — file-upload routes must cap size BEFORE reading the body into memory; post-read length check is a false guard (memory DoS), plus validate-then-charge rate limit ordering
- [Job-status capability authz](project-job-status-capability-authz.md) — GET /api/jobs/status returns PII from a UUID-capability (not ownership-checked) URL; accepted for P5, re-check the leak/ownership tradeoff when P6 reuses it
- [Cache-first async-mine dupe-enqueue](project-cache-first-async-mine-dupe-enqueue.md) — P6 roles/market read endpoints don't cache the miss → cold roles re-run the embedder + re-enqueue duplicate expensive mine jobs; also stale-refresh cache never invalidated post-mine
- [robots.txt fetch line-collapse](project-robots-txt-fetch-line-collapse.md) — crawlers reusing the HTML page-fetch helper for robots.txt collapse newlines → RobotFileParser silently ignores all Disallow; fake-checker tests hide it
- [Worker read-data to responder](project-worker-data-to-responder.md) — responder grounds only on WorkerResult.content, never .data; read/informational workers that stash data in .data (or drop the loop's final wrap-up) give hollow answers; tests asserting only .data hide it
