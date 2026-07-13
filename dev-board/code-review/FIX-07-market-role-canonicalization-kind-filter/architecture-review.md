# Architecture review — FIX-07-market-role-canonicalization-kind-filter · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | shared `kind` constants in a location with no `ingestion/`↔`agents/` cycle | `app/repositories/kb_kinds.py` — no heavy imports; both layers already depend on `repositories/` | none |
| A2 | Shared-KB corpus discrimination (my prior ruling) | reads over the `curated` corpus must discriminate producers by `meta["kind"]`, not `source_type` alone / rank | `_resolve_baseline` now takes top-`k=5` and returns the first hit whose parent `meta["kind"] == TAXONOMY_KIND`, else falls back | none — this is the direct enforcement of that ruling |
| A3 | §5.6 invariant | `role_profiles` keyed once per canonical role; mine-time and read-time canonicalization must agree | `resolve_canonical_role` (request-path) and `mine_role_requirements` share the one `_resolve_baseline`; a summary can no longer hijack canonicalization → no perpetual `202`/re-enqueue loop | none |
| A4 | DRY single-source | the three `_KIND` literals defined once, imported everywhere | `grep '_KIND = "'` → only `kb_kinds.py`; `learning_resources` re-exports for back-compat; taxonomy seed + market agent import | none |
| A5 | Layering (Router→Service→Agent/Repo) | fix stays in-agent; no new DB-driver access, no repo signature churn | `hybrid_search`/`hybrid_search_chunks` signatures unchanged; in-Python `kind` filter; no SQL JSONB parameter added | none |
| A6 | Producer symmetry | taxonomy docs stamp `kind` on document *and* chunks, matching the other two producers | `taxonomy_seed._upsert_occupations` stamps `meta["kind"]=TAXONOMY_KIND` on both `KbDocument` and each `kb_chunk` | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — repo-level constants module, no cross-layer leak
- [x] Honors locked decisions (Postgres+Redis only; native tool-calling extractor untouched; no ReAct parser) — no datastore/orchestration change
- [x] Interfaces-before-implementations — `SessionProvider`/`EmbeddingClient` seams untouched; no new implementation coupling
- [x] Budget posture respected — no new paid path; bounded `k=5`, no extra crawl

## Notes
- Minor (out of scope, not a blocker): the request-path `retrieve_market_intel` still reads the whole shared corpus via `shared_kb_document_ids(session)` without a `kind` filter — acceptable because it surfaces summaries+baseline as *grounding* for the responder, not for canonicalization. If a future turn needs to exclude learning-resource docs from market grounding, that is a separate follow-up, not this task.
- Minor (code-reviewer's domain, flagging for awareness): `_resolve_baseline` issues up to `k` `session.get(KbDocument, ...)` calls in the loop (bounded N+1 at k=5). Design-acceptable; leaving efficiency judgment to code-review.
- Consistent with my logged ruling `ruling-shared-kb-corpus-discrimination` — no new ruling required; this is the enforcement task that ruling anticipated.
