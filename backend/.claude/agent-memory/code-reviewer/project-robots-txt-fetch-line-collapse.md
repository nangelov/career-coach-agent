---
name: project-robots-txt-fetch-line-collapse
description: Crawlers reuse the HTML page-fetch helper to fetch robots.txt; the helper whitespace-collapses newlines, silently breaking RobotFileParser rule enforcement
metadata:
  type: project
---

Crawler mining code (market-intel §5.6, learning-resource §5.7) uses a shared page-fetch
helper (e.g. `market_agent._fetch_text`) that ends with `" ".join(text.split())` and, for
`text/plain`, runs bodies through `html_to_text`. When that same helper is injected as the
`RobotsChecker` fetcher (`RobotsChecker(fetch=lambda u: _fetch_text(client, u))`), robots.txt
loses all newlines → `RobotFileParser.parse(body.splitlines())` sees one mashed line and
**silently ignores every Disallow** (`can_fetch` returns True for everything).

**Why:** the page-extraction helper is designed to produce collapsed inert grounding text;
robots.txt needs line structure preserved. Reusing one helper for both defeats the guardrail.

**How to apply:** whenever a crawler wires robots.txt through its generic page fetcher, verify
the robots body preserves newlines. Watch for tests that only inject **fake** `RobotsChecker`
stand-ins (PermissiveRobots/DenyingRobots) — they pass while the real default fetch path stays
broken. Demand a test that drives the real fetch→parse against a multi-line Disallow. Relates
to [[project-crawler-fetcher-ssrf]].
