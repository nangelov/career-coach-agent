# Architecture review — P10-02-abuse-offtopic-pii-scrub · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Guardrail/scrub code lives in the right module | Scrub added in `app/agents/web_searcher.py` at the tool-invocation seam; reuses `app/llm/redaction.py`. No new module. | None |
| A2 | §7 / §7.6 PII scrub before external API | User-typed content scrubbed before it hits tools/external APIs | Query derived from `state.user_message` run through `redact_contact_details` before `search_tool.run(...)` dispatches to Tavily | None |
| A3 | DRY (§7.6 reuse SEC-08) | Reuse egress redaction primitive, not a second scrubber | Reuses `app.llm.redaction.redact_contact_details` — the same primitive SEC-08 egress + market miner use | None |
| A4 | §7.4 topic scoping | OFF_TOPIC→refuse, JOB_HUNTING→redirect, both reachable+tested | Audit-only: `OFF_TOPIC_REFUSAL` stamped by `_topic_guarded`, `route_after_planner` short-circuits; `JOB_HUNTING_REDIRECT_NOTE` appended by responder. Both paths tested (`test_topic_guardrail.py`). Classifier untouched (completion-pass constraint honored). | None |
| A5 | Scope boundary (KISS/YAGNI) | Scrub only true external-API seams | Market request-path is in-process (sentence-transformers + local pgvector); mining query is role-derived not user PII; dashboard tools write local DB. Correctly assessed as no-gap — Tavily is the only external hop carrying user text. | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo): scrub sits inside the worker at the tool-invocation seam; consumes `app.llm.redaction`
- [x] Honors locked decisions (Tavily pool reused verbatim, in-process embeddings for market-intel, no ReAct/classifier changes, Postgres+Redis only)
- [x] Interfaces-before-implementations: `SearchRunner` Protocol seam intact; scrub is a pure function reuse
- [x] Budget posture respected (no new dep — `redaction` is a pure in-tree module)

## Notes
- Consistent with prior rulings: [Tavily search pool] (P6-03) and [market-intel read-vs-mine split] (P6-04) — mining is Celery-only with role-derived queries, request-path never crawls. The engineer's no-gap assessment of those seams matches the settled design; no re-litigation.
- Ordering note (strip→blank-check→redact) preserves the blank-query short-circuit and leaves PII-free queries byte-identical, so no regression to existing search behaviour. Confirmed acceptable.
- Best-effort deterministic redaction is the design's accepted posture (§6.16 coverage limits) — no expectation of exhaustive PII coverage at this seam; the LLM-facing egress path remains the primary chokepoint. No follow-up.
