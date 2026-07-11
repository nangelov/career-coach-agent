# Code-reviewer memory index

- [Chat/LLM layer review checks](project-chat-llm-review-checks.md) — recurring things to verify in P1 chat/LLM/tool code (SSE injection, client-supplied history trust, lazy-DI races, native-tool-only)
- [Tool-arg parsing guards](project-tool-arg-parsing-guards.md) — half-guarded tool-call JSON parsers raise out of fail-soft nodes and 500 the turn; check every field's type guard
- [Crawler/fetcher SSRF](project-crawler-fetcher-ssrf.md) — server-side fetch of URLs from untrusted data (crawler, P6 extractors) is an SSRF surface; check scheme/IP allowlist + redirects, co-located Redis/Postgres raise the stakes
- [Frontend untrusted URL in href](project-frontend-untrusted-url-href.md) — citation/source URLs from web-search/crawl rendered into `<a href>` are a javascript:-scheme DOM-XSS sink; React doesn't sanitize, no CSP — require http/https scheme check
