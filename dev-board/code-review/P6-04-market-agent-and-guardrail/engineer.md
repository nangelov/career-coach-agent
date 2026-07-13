# Engineer report — P6-04-market-agent-and-guardrail · Revision 2

## Summary
Replaced v1's dropped "Job Search" concept with the v2 **Market Intelligence** capability
(design §5.6) and wired the planner's intent classification as the **topic guardrail** (§7.4).
Three pieces landed as one coherent change (tasks.md P6 bullets 4/5/10):

1. **`agents/market_agent.py`** — two halves split by cost: a request-path **MARKET_INTEL
   worker** (`retrieve_market_intel` / `make_market_node`) that *reads* the cached shared
   corpus (never crawls), and the **mining pipeline** (`mine_role_requirements`) — the
   taxonomy→crawl→extract→aggregate→persist job that populates `role_profiles` + embeds a
   summary into `kb_chunks`.
2. **`tasks/market.py`** — the thin Celery wrapper (`tasks.mine_role`), worker-local
   composition; mining is Celery-only, never request-path (§7.5).
3. **Topic guardrail** — `Intent`/`WorkerName` rework + an `OFF_TOPIC` graph short-circuit +
   a `JOB_HUNTING` responder redirect.

## Files changed
- `app/agents/state.py` — `Intent`: dropped `JOB_SEARCH`, added `MARKET_REQUIREMENTS`,
  `JOB_HUNTING`, `OFF_TOPIC`; `WorkerName`: `JOB_SEARCH`→`MARKET_INTEL`.
- `app/agents/planner.py` — `_INTENT_WORKERS`/`_INTENT_MAX_ITERATIONS` for the new intents
  (both market/job-hunting → `[MARKET_INTEL]`, off-topic → `[]`); prompt describes the new
  intents with §7.4 examples, tuned for low false-positives.
- `app/agents/market_agent.py` (new) — worker + mining pipeline (DI seams mirror
  `rag_agent`/`web_searcher`); forced-tool-call extraction over fenced untrusted text;
  LinkedIn hard-deny + robots + rate-limit + SSRF-guarded crawl + PII redaction.
- `app/ingestion/source_policy.py` (new) — shared, generic `RobotsChecker` + `HostRateLimiter`
  (stdlib `urllib.robotparser`; injected fetch/clock/sleep). P6-06 will import this.
- `app/ingestion/html_text.py` (new) — extracted the HTML→text helper here (DRY); `web_searcher`
  now imports it (its private copy removed).
- `app/repositories/market.py` (new) — `role_profiles`/`job_postings` repo helpers
  (upsert keyed on `canonical_role` / `(source,external_id)`; shared-KB reads).
- `app/tasks/market.py` (new) + `app/tasks/celery_app.py` — Celery task + `include`.
- `app/agents/graph.py` — real `market_intel` node; `OFF_TOPIC` short-circuit (`_topic_guarded`
  planner wrapper stamps a canned refusal, `route_after_planner` routes straight to
  `OUTPUT_GUARDRAIL`, `stream_response` emits it without an LLM call).
- `app/agents/responder.py` — `JOB_HUNTING` redirect framing note (no new LLM call).
- Stale-wording fixes: `app/schemas/chat.py`, `app/guardrails/untrusted_content.py`,
  `app/tools/internet_search.py`.
- Tests: new `test_market_agent.py`, `test_source_policy.py`, `test_topic_guardrail.py`;
  updated `test_agent_state/planner/graph/responder/chat_service/guest_upgrade`; `tests/fakes.py`
  gained `FreshSessionDBProvider` + `market_and_rag_session` + `scalar_one_or_none`.

## Key decisions
- **Worker reads cache; mining is Celery-only (§5.6/§7.5).** The MARKET_INTEL worker hybrid-searches
  the shared KB (`user_id IS NULL`) and enriches with the `role_profiles` rows the retrieved
  summary chunks reference (via `meta.canonical_role`). It never triggers a crawl.
- **OFF_TOPIC mirrors the input-guardrail short-circuit shape** (per task): the planner node stamps
  the refusal (only the async real `Planner` is wrapped, so the sync default graph stays sync-invokable),
  routing skips workers **and** responder, and `stream_response` emits the canned answer — the
  streamed path is handled too (a node-set response alone is ignored by the responder stream).
- **JOB_HUNTING = same worker, responder redirects** (§7.4 "redirect ≠ refusal") — no listings tool exists.
- **LinkedIn hard-deny composes with the SSRF guard** via `deny_hosts=DEFAULT_DENY_HOSTS|{linkedin.com}`
  + `.linkedin.com` suffix (rejected pre-DNS); robots + rate-limit via the shared `source_policy`.
- **Extraction is forced-tool-call over fenced text** (§7.3, mirrors planner); postings are
  `redact_contact_details`-stripped (§7.6) **before** persistence.
- **Reused, not duplicated:** `LLMCompleter`/`SearchRunner`/`SessionProvider` protocols, `hybrid_search`,
  `add_kb_chunk`, `build_guarded_client`/`read_capped`, `fence_untrusted`, `redact_contact_details`.

## How to verify
- `cd backend && .venv/bin/python -m pytest tests/test_market_agent.py tests/test_source_policy.py
  tests/test_topic_guardrail.py tests/test_agent_planner.py tests/test_agent_graph.py -q`
- Grep: `grep -rn JOB_SEARCH app/agents app/api tests` → only the state.py docstring explaining the rename.
- CLI (live DB/keys): `python -m app.tasks.market --role "AI Solution Architect"`.

## Tests (final step — mandatory)
- Full suite: `.venv/bin/python -m pytest -q` → **550 passed, 57 skipped** (revision 2: +2 new
  robots/plain-text regression tests; skips = live-DB/ML, unchanged). No failures.
- `.venv/bin/ruff check app/agents/market_agent.py tests/test_market_agent.py` → All checks passed.
  `ruff format --check` → already formatted.
- `.venv/bin/mypy app/agents/market_agent.py` → Success, no issues.

## Self-check
- [x] Meets acceptance criteria (worker + mining pipeline w/ DI fakes; Celery task not called
      from request path; SSRF+robots+LinkedIn-deny+rate-limit tested; fenced+forced-tool extraction;
      PII stripped before persist; `role_profiles` upsert on `canonical_role` + `kb_chunks` summary;
      no leftover `JOB_SEARCH`; OFF_TOPIC short-circuit + JOB_HUNTING redirect; §7.4 example tests).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (DB access via
      `repositories/market.py` + `vector_search`; worker/pipeline inject collaborators).
- [x] Tests/lints pass (pasted above).

## Response to review (revisions only)

### Revision 2 (code-review.md CHANGES_REQUESTED)

**C1 (major) — robots.txt silently disabled in the real crawl path — FIXED.**
Root cause confirmed: the default checker fetched `robots.txt` through `_fetch_text`, whose final
`" ".join(text.split())` collapses every newline (and for `text/plain` also ran `html_to_text`),
so `RobotFileParser.parse(body.splitlines())` got one mashed line and dropped every `Disallow`.
Fix in `app/agents/market_agent.py`:
- Split `_fetch_text` into `_fetch_decoded` (SSRF-guarded stream + byte/timeout cap + decode,
  returns the body **verbatim** with line structure intact) and the page-text step on top of it.
- Added `_fetch_robots_body` — returns the decoded body **without** whitespace-collapse or HTML
  strip, so `RobotFileParser` parses real line-oriented rules.
- The production default checker is now
  `RobotsChecker(fetch=_guarded_robots_fetch(client, limiter))` (was `lambda url: _fetch_text(...)`),
  so the real Celery mining path (`mine_role_requirements(robots=None)` → this default) enforces
  robots.txt for real, not only in tests.
- Added `test_real_robots_checker_over_guarded_fetch_enforces_disallow`: drives the **real**
  `RobotsChecker` + `_guarded_robots_fetch` + `_fetch_robots_body` over the SSRF-guarded client
  against a multi-line `robots.txt` with `Disallow: /private/`, and asserts `/private/...` → blocked,
  `/public/...` → allowed. This test fails against the old collapse-based fetch, locking the regression.

**C2 (minor) — robots fetch not rate-limited — ADDRESSED.**
The new default fetcher `_guarded_robots_fetch(client, limiter)` calls `await limiter.acquire(url)`
before each `robots.txt` fetch, so the robots request (once per host, on cache miss) and the
following page fetch both go through the **same** per-host limiter — no back-to-back host hits.
Gating lives in the injected fetcher (not the loop), so only real network fetches are spaced and
cached-robots hosts incur no wasted wait.

**C3 (nit) — text/plain misrouted through HTML extraction — FIXED.**
`_fetch_text` now branches on `"html" in content_type` only; genuine `text/plain` bodies are used
as-is (whitespace-collapsed) and no longer passed through `html_to_text`. Added
`test_fetch_text_treats_plain_text_as_already_plain` (a `<and>` token that `html_to_text` would eat
survives verbatim) to lock the behavior.
