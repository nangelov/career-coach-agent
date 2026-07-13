# Architecture review — P6-06-learning-resource-corpus · engineer revision 1

## Verdict: APPROVED

Design-conformant. The learning-resource corpus (§5.7 / §6 decision 20) lands as a faithful
sibling of the P6-04 market-intel miner: injectable testable core in `ingestion/` + thin
Celery wrapper + repository-owned read, reusing every already-landed seam. No unwind-expensive
deviation. Two logged follow-ups below, both cheap and pre-owned by the engineer.

## Conformance table

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| C1 | Target structure (§8) | Corpus core in `ingestion/`, read in `repositories/`, task in `tasks/` | `ingestion/learning_resources.py` + `ingestion/crawl.py` core, `repositories/learning_resources.py` read, `tasks/learning_resources.py` wrapper | none |
| C2 | Layering (§8) | Services/agents never touch driver; DB via repo/session boundary | Read is a repo helper; writes reuse `add_kb_chunk` + inline upsert (same as blessed `market_agent`/`taxonomy_seed`); caller owns txn | none (see N1) |
| C3 | Shared-corpus data ownership (§4/§5.7) | `user_id IS NULL`, `source_type="curated"`, skill-keyed, global+amortized | `CURATED_SOURCE_TYPE="curated"`, `user_id=None`, `skill_keys` + `kind` in `meta`; `list_resources_for_skill` JSONB `@>` filters on kind + skill | none |
| C4 | Corpus discrimination | Distinct shared corpus co-existing with taxonomy/role-profiles under `curated` | `meta.kind="learning_resource"` marker mirrors `market_agent`'s `ROLE_PROFILE_KIND`; read filters on it → no cross-corpus leak | none |
| C5 | Untrusted content (§7.3 / §6.14) | Crawled pages fenced as data; extraction forced tool-call, no free-text parse | `fence_untrusted(...)` before LLM; `tool_choice` forces `record_learning_resource`; system prompt reasserts data-not-instructions | none |
| C6 | Native tool-calling (§6, locked) | Constrained tool schema, no ReAct parser | Forced-function schema + `_parse_resource` off structured `tool_calls`; no text parsing | none |
| C7 | SSRF / robots / rate-limit reuse (§7.2 / §10) | Import `source_policy` + `ssrf_guard`, don't re-implement | Reuses `RobotsChecker`/`HostRateLimiter`, `build_guarded_client`/`read_capped`; every fetch guarded; robots body line-preserved | none |
| C8 | Mining is Celery-only (§7.5) | Never on a user-facing turn | `tasks.mine_learning_resources` + CLI only; grep of `api/`+`services/` → no callers | none |
| C9 | TTL refresh (§5.7) | Staleness marker for periodic re-mine | `refreshed_at` in `meta`; delete-before-insert on normalized-URL key → re-mine updates, not dupes | none |
| C10 | Budget posture (§11) | Free/OSS/self-hosted; bounded cost | Tavily pool reuse, in-process ST embeddings, provider allowlist + bounded results/page caps | none |
| C11 | Embeddings / vector consistency (§6.3) | In-process ST, dim via `add_kb_chunk` | `SentenceTransformerEmbeddingClient` + `add_kb_chunk` (no re-specified dim) | none |
| C12 | No new migration | Reuse P2 `kb_documents`/`kb_chunks` | No migration; JSONB containment read needs none | none |
| C13 | Phase fit / P7 non-coupling | Make corpus skill-queryable, don't wire PDP citation | `list_resources_for_skill` is the read seam only; no citation logic | none |
| C14 | Celery `include` wiring | Worker knows the task module | `app.tasks.learning_resources` appended to `celery_app.include` | none |

## Cross-cutting checklist
- Interfaces before implementations: extraction/search/embed/DB all injected Protocol/seam params (`LLMCompleter`, `SearchRunner`, `EmbeddingClient`, `SessionProvider`) — swappable, fake-driven in tests. OK.
- Locked v2 decisions (LangGraph N/A here, native tool-calling, Postgres+Redis only, in-process embeddings, Celery, Tavily pool): all honored. OK.
- DRY/SoC/KISS/YAGNI: `crawl.py` extraction removes a would-be second robots/page-fetch copy (DRY-positive, and prevents re-introducing the market C1 line-collapse bug). Provider allowlist keeps scope + cost bounded (YAGNI). OK.
- Data ownership (§4): shared rows only; no guest/user-scoped path touched. OK.

## Notes
- **N1 (SoC nit, blessed by precedent — no action):** the idempotent delete-before-insert and `KbDocument` construction live inline in the pipeline's `_persist` rather than a repository write helper. This exactly matches the already-DONE `market_agent`/`taxonomy_seed` composition-root precedent (see agent-memory `pattern-celery-ingest-composition-root`); the read that a downstream consumer needs is correctly in `repositories/`. Consistent, so approved as-is.
- **N2 (follow-up, engineer-owned):** `crawl.py` is the new shared transport, but `market_agent` still carries equivalent private page/robots helpers (task forbade modifying it). Consolidating `market_agent` onto `crawl.py` is the documented follow-up — track it so the duplicate doesn't drift.
- **N3 (design-positive):** the `PROVIDER_HOSTS` allowlist (LinkedIn Learning deliberately excluded, §10 ToS) is a good realization of §5.7 "prefer official providers over marketing pages" and also bounds Tavily/crawl cost.
