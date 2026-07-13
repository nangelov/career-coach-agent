# Architecture review — P6-04-market-agent-and-guardrail · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | market code in `agents/` + `tasks/` + `repositories/`; DB off the agent/service layer | `agents/market_agent.py` (worker+pipeline), `tasks/market.py` (Celery+CLI), `repositories/market.py` (all SQL), `ingestion/source_policy.py`, `ingestion/html_text.py` | none |
| A2 | §5.6 pipeline | taxonomy-baseline → crawl delta → PII-strip → fenced LLM extract → aggregate → upsert `role_profiles` + embed into `kb_chunks(user_id NULL)` | `mine_role_requirements` implements each stage in order; baseline from curated taxonomy KB, forced-tool extraction, freq/weight/evidence aggregate, upsert on `canonical_role`, summary embedded via `add_kb_chunk` | none — matches §5.6 diagram step-for-step |
| A3 | §7.5 read-vs-crawl | "no user-facing turn triggers uncached crawling" | request-path `retrieve_market_intel` only reads shared KB + `role_profiles`; mining is Celery-only (`tasks/market.py`), never imported on a request path | none |
| A4 | §7.4 topic guardrail | planner intent = guardrail, no extra LLM call; `OFF_TOPIC`→refuse, `JOB_HUNTING`→redirect ≠ refusal | `_topic_guarded` stamps canned `OFF_TOPIC_REFUSAL` + `route_after_planner` short-circuits to OUTPUT_GUARDRAIL (no workers/responder); `JOB_HUNTING` runs MARKET_INTEL, responder appends `JOB_HUNTING_REDIRECT_NOTE`; low-FP prompt tuning | none — short-circuit mirrors input-guardrail shape exactly |
| A5 | §7.3 untrusted content | crawled posting text fenced before any LLM call; forced tool-call, no free-text parse | `_extract_requirements` wraps text in `fence_untrusted` then forces `record_requirements` tool_choice; `_parse_skills` never raises | none |
| A6 | §7.6 third-party PII | recruiter contact stripped before persist to `job_postings` | `redact_contact_details(text)` applied in `_fetch_postings` before `_Posting` built and before `upsert_job_posting` | none |
| A7 | §10 source policy | robots.txt respected, per-host rate limit, LinkedIn hard-deny | shared `source_policy.RobotsChecker`/`HostRateLimiter`; LinkedIn via `DEFAULT_DENY_HOSTS\|{linkedin.com}` + `.linkedin.com` suffix composed into `build_guarded_client` (pre-DNS reject) | none |
| A8 | §7.2 single guarded client | reuse `ssrf_guard.build_guarded_client`/`read_capped`, no second HTTP path | one guarded client per run; robots fetch injected through the same client; no hand-rolled second client | none |
| A9 | §3 intent list / data ownership | intent vocab incl. market-requirements/off-topic/job-hunting; `role_profiles` global, not user-scoped; guests see shared corpus | `Intent` reworked (JOB_SEARCH dropped, MARKET_REQUIREMENTS/JOB_HUNTING/OFF_TOPIC added); `WorkerName.MARKET_INTEL`; nothing keyed on `user_id`; shared reads via `user_id IS NULL` | none — `dashboard` correctly deferred to P8 |
| A10 | rename hygiene | no leftover `JOB_SEARCH` value/worker | grep: only two explanatory docstring mentions in `state.py`; model `jobs.py`→`market.py` consistent with P6-02 migration `0007` | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — agents/tasks inject collaborators; all SQL isolated in `repositories/market.py` (helpers flush, caller owns commit)
- [x] Honors locked decisions — native forced tool-calling (no ReAct parser), LangGraph typed-state fan-out unchanged, Postgres(pgvector+JSONB)+Redis only, in-process sentence-transformers embedder, Celery for the crawl job, LLMRouter as extractor
- [x] Interfaces-before-implementations — `LLMCompleter`/`SearchRunner`/`SessionProvider` Protocols + `EmbeddingClient`/`RobotsChecker`/`HostRateLimiter` injected; unit-testable with fakes, no hard-coded clients (mirrors rag_agent/web_searcher seams)
- [x] Budget posture — stdlib `urllib.robotparser` (no new heavy dep), taxonomy-first, extract-once-per-role amortization, deferred heavy imports keep the Celery `include` module light

## Notes
- Minor (accepted, no action): the mined role-profile summary is embedded with `source_type="curated"` — the `ck_kb_documents_source_type` check allows only curated/user_cv/crawled. A synthesized aggregate is defensibly "curated" (not raw crawled evidence), and a distinct value would need a migration. Blessed as-is; recorded in memory.
- DRY win: `html_to_text` lifted to `ingestion/html_text.py` and `web_searcher` now imports it (private copy removed) — good SoC.
- Follow-up for P6-06 (learning-resource corpus): it MUST import `ingestion/source_policy.py`, not duplicate robots/rate-limit — the module was deliberately kept generic for this. Flagged for the sibling task, not a blocker here.
- LinkedIn robots fetch also routes through the SSRF-guarded client, so a LinkedIn URL is dropped at the page fetch regardless of robots — the hard-deny holds end-to-end.
