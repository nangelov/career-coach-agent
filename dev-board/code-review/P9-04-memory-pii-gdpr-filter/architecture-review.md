# Architecture review — P9-04-memory-pii-gdpr-filter · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | new deterministic filter lives in a canonical module | `app/memory/gdpr_filter.py` — pure module inside the `memory/` package alongside `learn.py`/`store.py` | none |
| A2 | §7.6 PII redaction in the learn loop | durable `user_memories` PII-free | `redact_contact_details` reused (not re-implemented) at the write boundary in `_gate_candidate`; contact PII transforms text, memory survives | none |
| A3 | §7.6 GDPR Art. 9 exclusion | health/disability/ethnicity/religion/union/sexuality never durable, in-turn only | `special_category_of` drops the candidate before `add_memory`/`update_memory`; responder/recall untouched so "in-turn only" holds by non-persistence | none |
| A4 | Reuse existing egress chokepoint (constraint) | no move/refactor of `LLMRouter`/`redact_messages` egress redaction (§6.16) | function reused, call site untouched; engineer correctly declined a duplicate input-side pass since egress already redacts to the extractor LLM | none |
| A5 | Budget posture (§11) / repo classifier tier | deterministic regex, no ML/NER dep, "coarse now, real classifier later" (mirrors `guardrails/heuristics`, P10) | compiled keyword/regex per category, no I/O, honest-limitations docstring, over-drop failure direction | none |
| A6 | Locked decisions | native tool-calling extractor, no ReAct, Postgres+Redis only | extractor/store paths untouched; gate is a pure pre-write filter | none |
| A7 | Data ownership (§4) | guests stay Redis-only, no durable learn | unchanged — `run_learn_from_turn` still `skipped` for guest/malformed uid | none |
| A8 | Blast radius | P6 `job_postings` third-party-PII strip is a separate pipeline | confirmed unaffected (market_agent `_crawl_and_redact`); recall/CRUD/purge untouched | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (pure leaf module below the service layer; `memory/` reusing `llm/redaction` is a leaf-utility import, consistent with P9-03's existing `llm/*` imports)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; native tool-calling extractor intact)
- [x] Interfaces-before-implementations (reuses existing seams; no new store/LLM surface)
- [x] Budget posture respected (deterministic regex, zero new deps)

## Notes
- **Blessed seam relocation.** Prior ruling ([[pattern-memory-learn-step]]) flagged the P9-04 seam as `MemoryExtractor.propose`. The engineer instead gated at `_apply_candidate` (the single write boundary). This is a *stronger* choice and was explicitly permitted by the task ("or the point immediately consuming its output"): `_apply_candidate` also covers the down-vote-reason synthesised candidate, which never passes through `propose`. Both extractor output and the negative-preference path are now covered by one chokepoint — the correct durable-store guarantee.
- **Redact-then-classify order** is sound: redaction markers carry no Art. 9 terms, so the two gates cannot mask each other; verified by test.
- Design risk (logged, not blocking): coarse keyword lists will miss euphemism/paraphrase/non-English and can over-drop benign career text (e.g. "church" in an unrelated context). This is the accepted "coarse now" tier and the safe (over-drop) failure direction for Art. 9; a real special-category classifier remains a later dedicated investment, same tier as the P10 injection classifier.
