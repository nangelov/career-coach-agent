# Code review — P10-02-abuse-offtopic-pii-scrub · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | app/agents/web_searcher.py:142 | `redact_contact_details` includes a name-header/`Name:` heuristic; a query that is *only* a "Firstname Lastname" line (e.g. researching a named person/company contact) would be replaced by `[NAME REDACTED]`, degrading that search. Safe-direction and best-effort, so acceptable. | No change required — noting the over-redaction edge for future awareness. Do not fork the SEC-08 primitive to fix. |

## Notes
- **Part 1 (abuse/off-topic) — audit verified, not just asserted.** `OFF_TOPIC` → `_topic_guarded` stamps `OFF_TOPIC_REFUSAL` and `route_after_planner` short-circuits before any worker/responder LLM call; `test_off_topic_turn_streams_refusal_without_calling_the_responder` asserts `responder_router.stream_messages == []` and finish_reason `off_topic`. `JOB_HUNTING` → responder runs and appends `JOB_HUNTING_REDIRECT_NOTE` (responder.py:263); `test_job_hunting_turn_is_not_short_circuited` asserts the responder DID run. Refusal-vs-redirect distinction is real and covered. Correctly left the classifier untouched per the completion-pass constraint.
- **Part 2 (PII scrub) — gap real, fix correct and minimal.** `search_and_crawl` called Tavily directly, bypassing the SEC-08 router chokepoint, so pasted contact PII reached the external API unscrubbed. Fix scrubs the derived query via `redact_contact_details` (DRY — same primitive as the egress boundary and market miner) before dispatch. Strip-then-check-blank-then-redact ordering preserves the existing blank-query short-circuit; no behavior change for PII-free queries (existing web-searcher tests pass unmodified).
- **Audit of other external seams independently confirmed.** Only two `search.run` callers exist: `web_searcher` (now scrubbed) and `market_agent.py:504`, whose query is role-derived (`f"{canonical_role} job requirements"`), not user PII, and whose crawled postings are already §7.6-redacted. Request-path MARKET_INTEL and dashboard tools stay in-process/local — no external hop carrying user text. No missed seam.
- **New test is meaningful:** asserts raw email/phone absent, `[EMAIL REDACTED]`/`[PHONE REDACTED]` present, and non-PII substance (`ML roles`) preserved. Ran `test_query_is_pii_scrubbed_before_dispatch` + `test_topic_guardrail.py` locally → 3 passed. Engineer reports full suite 889 passed / 83 skipped, ruff/format/mypy green.
- Crawled page text remains inert (only surfaced in `content`/`citations`), SSRF-guarded, fail-soft — unchanged and still correct.
