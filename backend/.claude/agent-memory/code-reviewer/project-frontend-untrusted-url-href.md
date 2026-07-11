---
name: project-frontend-untrusted-url-href
description: Frontend renders citation/source URLs from untrusted web-search/crawled content into <a href> — check for javascript:-scheme DOM-XSS
metadata:
  type: project
---

Citation/source URLs shown in the chat UI originate from **untrusted third-party
content**: `backend/app/agents/web_searcher.py` maps `item.get("url")` from
search-provider results and crawled pages straight into `SourceCitation.url`, which is
streamed to the frontend on the `done` event's `citations[]`.

When the frontend renders these as `<a href={citation.url}>`, that is a DOM-XSS sink:
- React does **not** sanitize `href`; a `javascript:` or `data:text/html` scheme is
  rendered and clickable. React 19 only logs a dev-only warning, does not block.
- No CSP is configured on the Next.js app (`frontend/next.config.*`), so nothing
  mitigates it downstream.

**Why:** this app deliberately ingests crawled/web content (see [[project-crawler-fetcher-ssrf]]);
any field derived from it reaching a browser sink is attacker-influenceable.

**How to apply:** whenever a PR renders a URL that traces back to search/crawl/LLM
output as a link (href, window.open, `<link>`), require scheme validation — only allow
`http:`/`https:` (parse with `new URL()` and check `protocol`), else render as plain
text. Same applies to `src`. First seen: P4-09 citation list.
