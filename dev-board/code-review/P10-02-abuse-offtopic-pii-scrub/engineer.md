# Engineer report — P10-02-abuse-offtopic-pii-scrub · Revision 1

## Summary
Two-part input-guardrail completion pass (design §7 / §7.4 / §7.6).

**Part 1 — abuse/off-topic filter (audit, no code change needed).** Audited the topic-scoping
path end-to-end and found it already complete and correctly-shaped:
- `OFF_TOPIC` → **refused**. The planner's intent classification is the topic guardrail;
  `_topic_guarded` (graph.py) stamps `OFF_TOPIC_REFUSAL` and `route_after_planner` short-circuits
  to the terminal tail, skipping every worker **and** the responder LLM call. Covered by
  `test_off_topic_turn_streams_refusal_without_calling_the_responder`.
- `JOB_HUNTING` → **redirected, not refused**. Routes to the MARKET_INTEL worker (a market-
  requirements read), and the responder appends `JOB_HUNTING_REDIRECT_NOTE` (responder.py) so the
  answer gives market requirements + steers back to development — a redirect, distinct from the
  refusal. Covered by `test_job_hunting_turn_is_not_short_circuited`.
Both outcomes are reachable, tested, and use the right (distinct) response shapes. No gap found,
so per the "completion pass, not a rewrite" constraint I did **not** touch the classification
mechanism.

**Part 2 — PII scrub before content hits an external API (gap found + closed).** Audited every
seam where user-typed/profile content flows into a tool call or external API:
- `internet_search` / Web Searcher — **GAP.** `search_and_crawl` took the raw `user_message` as
  the query and called Tavily **directly**, bypassing the LLM router — so SEC-08's router-chokepoint
  `redact_messages` never covered it. A user who pasted an email/phone into chat forwarded it to
  Tavily unscrubbed. **Closed** by scrubbing the query with the SEC-08 primitive
  (`redact_contact_details`) at the dispatch seam, before `search_tool.run(...)`.
- market-intel — **no gap.** The request-path MARKET_INTEL worker never crawls; it embeds
  in-process (sentence-transformers) and hybrid-searches local Postgres — nothing leaves the
  process. The mining pipeline's search query is role-derived (`f"{canonical_role} job
  requirements"`), not user PII, and crawled postings are already redacted (§7.6, pre-existing).
- dashboard tools — **no gap.** Inputs are model-generated structured args written to the local
  `DashboardService`/DB; no external API.

## Files changed
- `app/agents/web_searcher.py` — scrub the derived search query with `redact_contact_details`
  before dispatching to Tavily; import + docstring (module + `search_and_crawl`) updated to
  document the PII-scrub boundary and why it reuses (not duplicates) the SEC-08 primitive.
- `tests/test_web_searcher.py` — new `test_query_is_pii_scrubbed_before_dispatch` (email/phone in
  the message are replaced by `[… REDACTED]` markers before the query reaches the search tool;
  non-PII substance preserved).

## Key decisions
- **Reuse SEC-08's `redact_contact_details`, don't build a second scrubber** (task DRY constraint,
  §7.6). Same deterministic best-effort primitive the LLM egress boundary and market miner already
  use.
- **Scrub only the true external-API seam.** The market request-path and dashboard tools stay
  in-process/local, so scrubbing there would be dead weight (KISS/YAGNI) — the design bullet is
  "before content hits tools or **external APIs**", and Tavily is the only external hop carrying
  user text.
- **Strip-then-check-then-redact ordering** preserves the existing blank-query short-circuit;
  a PII-free query is returned unchanged so normal search behaviour (and existing tests) are
  unaffected.
- **No topic-guardrail changes** — audit showed it already meets acceptance; touching the
  classifier would violate the completion-pass constraint.

## How to verify
```
cd backend && . .venv/bin/activate
ruff check app/agents/web_searcher.py tests/test_web_searcher.py
ruff format --check app/agents/web_searcher.py tests/test_web_searcher.py
mypy app/
python -m pytest tests/test_web_searcher.py tests/test_topic_guardrail.py tests/test_llm_redaction.py -q
python -m pytest -q
```

## Tests (final step — mandatory)
- `ruff check` + `ruff format --check` (changed files) → All checks passed / already formatted.
- `mypy app/` → Success: no issues found in 149 source files.
- `python scripts/check_curated_deps.py` → Curated-dependency guard OK (no new dep — `redaction`
  is a pure in-tree module).
- `python -m pytest -q` (full suite) → **889 passed, 83 skipped** (+1 new test; skips are the
  unchanged live-DB/ML set with no Postgres/model locally). Existing topic-guardrail and web-
  searcher tests pass unmodified.
- No failures; no test weakened.

## Self-check
- [x] Meets acceptance criteria: off-topic refused + job-hunting redirected (both pre-existing,
  tested); user-typed content scrubbed before the external search API using the SEC-08 primitive;
  new test proves email/phone scrub before dispatch; ruff/format/mypy/pytest green.
- [x] No secrets; Router→Service→Agent/Repo layering respected (scrub added inside the worker at
  the tool-invocation seam; reuses `app.llm.redaction`).
- [x] Tests/lints pass (pasted above).
