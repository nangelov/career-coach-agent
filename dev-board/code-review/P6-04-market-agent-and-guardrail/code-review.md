# Code review — P6-04-market-agent-and-guardrail · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major → RESOLVED | app/agents/market_agent.py:556-582, 492 | Robots.txt is now fetched via `_fetch_robots_body` (→ `_fetch_decoded`), which returns the body **verbatim** with newlines intact; the production default checker is `RobotsChecker(fetch=_guarded_robots_fetch(client, limiter))`. `RobotFileParser.parse(body.splitlines())` now receives real line-oriented rules, so `Disallow` is enforced in the real Celery mining path (`mine_role_requirements(robots=None)` → this default), not only in tests. Verified by `test_real_robots_checker_over_guarded_fetch_enforces_disallow`, which drives the real checker + guarded fetch against a multi-line robots.txt and asserts `/private/` → blocked, `/public/` → allowed. | Done. |
| C2 | minor → RESOLVED | app/agents/market_agent.py:568-582 | The default robots fetcher now calls `await limiter.acquire(url)` before each robots fetch (once per host, on cache miss), sharing the same per-host `HostRateLimiter` as the page fetch — no back-to-back host hits. Cached-robots hosts incur no wasted wait since the fetch (and its acquire) only runs on cache miss. | Done. |
| C3 | nit → RESOLVED | app/agents/market_agent.py:541-553 | `_fetch_text` now branches on `"html" in content_type` only; genuine `text/plain` bodies bypass `html_to_text` and are used as-is. Verified by `test_fetch_text_treats_plain_text_as_already_plain` (a `<and>` token that `html_to_text` would strip survives). | Done. |

## Notes
- C1 root cause and fix are correct and cleanly separated: `_fetch_decoded` (verbatim body) is the shared primitive; `_fetch_text` layers HTML-extraction + whitespace-collapse for page text, while `_fetch_robots_body` deliberately skips both. The regression test drives the **real** wiring end-to-end (not a fake checker), so it locks the defect — it would fail against the old collapse-based fetch.
- No new issues introduced. Page fetches still use `_fetch_text` (line 504); only the robots path was diverted. SSRF guard, byte/timeout caps, LinkedIn hard-deny, PII redaction-before-persist, fenced+forced-tool extraction, and shared-corpus-only reads all remain intact from revision 1.
- Verified locally: `pytest tests/test_market_agent.py tests/test_source_policy.py -q` → 21 passed. Engineer reports full suite 550 passed / 57 skipped, ruff + mypy clean on changed modules.
- Prior-revision security posture (rev 1 Notes) still stands and is unchanged by this fix.
