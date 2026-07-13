# Memory index

- [Session memory placement ruling](ruling-session-memory-placement.md) — Persistent (Redis) store impls belong in repositories/, not services/; ABC seam in services/ is OK
- [Client-supplied history trust boundary](ruling-client-history-trust.md) — Client-supplied chat history must not carry system/tool roles or forged tool_calls
- [P1 walking-skeleton scope blessings](pattern-p1-walking-skeleton.md) — Accepted interim patterns for P1 chat skeleton (hardcoded prompt, lazy DI in router module, in-memory seam)
- [message_id feedback-key ruling](ruling-message-id-feedback-key.md) — §5.5 id stamps only terminal answers; get_message is P1 plumbing, durable feedback lookup moves to Postgres in P2/P9
- [Planner classify/route split](pattern-planner-classify-route-split.md) — Blessed: LLM classifies Intent, code derives worker routing deterministically; keep the seam for P4-04..P4-06
- [Worker node DI + scope shape](pattern-worker-node-di-scope.md) — P4 worker template: Protocol DI seam, no rogue pool, explicit access allow-list, retrieval-only, fail-soft; apply to P4-05/06
- [Web-searcher P6 scope split](ruling-web-searcher-p6-scope-split.md) — P4-05 rightly defers §3 structured role-page extraction + Postgres write + Celery to P6; access allow-list N/A (public web)
- [Responder P4-06 scope](ruling-responder-p4-06-scope.md) — Blessed: injected LLM seam, untrusted-content fencing, citations pass-through; P9 must wire state.memory into responder + chat-endpoint owns streamed guardrail/memory tail
- [Input guardrail P4-08 seam](ruling-input-guardrail-p4-08-seam.md) — Blessed: screen_input->SafetyVerdict seam, one conditional edge, block routes to OUTPUT_GUARDRAIL skipping planner/workers; P10 swaps detection only
- [Curated CI light deps ruling](ruling-curated-ci-light-deps.md) — Light always-used deps (incl. authlib/langgraph) curated in; only heavy ML (docling/torch) stay absent; pytest executes module-scope imports so they must be present; fix stale "excluded/Any" comments everywhere; CI list == Makefile
- [Celery ingest composition-root pattern](pattern-celery-ingest-composition-root.md) — Blessed P5 background-job template: enqueue Protocol port + injected async core + worker-local composition root + guest preview-no-persist; reuse for P6 crawl / P9 memory-learn
- [Job-status capability authZ ruling](ruling-job-status-capability-authz.md) — P5-06 job-status endpoint uses capability (unguessable task_id) authZ; cheap-to-tighten, but §7 ownership map is a live P6 follow-up — don't re-bless silently
- [Shared-KB corpus discrimination ruling](ruling-shared-kb-corpus-discrimination.md) — Multiple shared corpora share source_type="curated", discriminated by meta.kind; reads must filter on kind (P6-06 learning resources)
- [Market cache-key raw-param ruling](ruling-market-cache-key-raw-param.md) — Roles response cache keys on cheap raw-param norm, not taxonomy canonical (canonicalize reads DB); deliberate, don't flag
- [Market-query rate-limit action ruling](ruling-market-query-rate-limit-action.md) — /api/roles requirements reuses RateLimitAction.MESSAGE; dedicated MARKET_QUERY is a live follow-up, not a blocker
