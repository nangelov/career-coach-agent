# Architecture review — P7-01-pdp-agent · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | agent in `agents/`, contract in `schemas/` | `app/agents/pdp_agent.py` + `app/schemas/pdp.py`; exported via `agents/__init__.py` | Conforms. |
| A2 | Layering (Router→Service→Agent/Repo) | no DB driver in agent; go through `repositories/` | Agent reads corpus only via `repositories.learning_resources.list_resources_for_skill`, session handed in by injected `ResourceLookup`; no SQLAlchemy driver calls in body | Conforms. |
| A3 | No ReAct parser (locked §6) | native tool-calling only, no scaffolding can leak | Forced `record_pdp` tool call; model writes bodies only, `##` headings added deterministically by `PdpContent.to_markdown` — scaffolding structurally impossible | Conforms — strongest form of the acceptance #2 requirement. |
| A4 | LLM plumbing (P1) | reuse `LLMClient`/router, no new plumbing | Depends on `LLMCompleter` Protocol (structurally the P1-02 `LLMRouter`), injected; `complete(...)` signature matches exactly | Conforms. |
| A5 | Untrusted-content contract (S2 / §7.3) | reuse existing `fence_untrusted`, no new fence | Profile + market/learning blocks fenced via `fence_untrusted(label, blocks, origin=...)`, same pattern as `market_agent`/`responder`; goal/date are the trusted user turn | Conforms. |
| A6 | Grounded, not hallucinated (§5.6/§5.7) | gap from `SkillsGapResult.gap`; training from real corpus resources, cited | Gap driven by ranked `SkillGap` items; resources pulled by skill-keyed P6-06 lookup, deduped by URL, carried structurally in `PdpContent.resources` for deterministic citation | Conforms. |
| A7 | Interfaces before implementations | real seams for LLM + DB | `LLMCompleter` + `ResourceLookup` structural Protocols; unit tests inject fakes, P7-03 wires singletons | Conforms. |
| A8 | Data ownership (§4) | shared corpus is `user_id IS NULL`; `pdps` schema untouched | `list_resources_for_skill` enforces `user_id.is_(None)` + `curated`; `pdps` migration untouched, `PdpContent.model_dump()` fits `content` JSONB | Conforms. |
| A9 | Graceful degradation (§5.1) | missing profile / unmined role / no resources → no crash | `PdpContent.status` maps all three; LLM failure → honest fallback sections; never raises — P7-03 branches on status | Conforms. |
| A10 | Phase fit (P7) | agent module + tests only, no PDF/endpoint/FE | PDF builder (P7-02), `/api/pdp` (P7-03), FE (P7-04) all left out; heading contract kept renderable for the P7-02 validator | Conforms. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — repo helper via injected session, no driver.
- [x] Honors locked decisions (no ReAct parser — forced tool-call + deterministic headings; Postgres+Redis only; in-process embeddings not needed here — skill-keyed lookup avoids the ML stack).
- [x] Interfaces-before-implementations (`LLMCompleter`, `ResourceLookup` Protocols; repository seam).
- [x] Budget posture respected (no new LLM/embed plumbing; skill-keyed JSONB read, no second similarity search).

## Notes
- **DRY follow-up (minor, cheap-to-fix-later — not blocking):** `ResourceLookup` is byte-for-byte identical in shape to the existing `app.agents.rag_agent.SessionProvider` (`def session() -> AbstractAsyncContextManager[AsyncSession]`), which `market_agent` already reuses by import. The PDP agent defines a fresh, structurally-identical Protocol instead. Because both are structural, the same provider satisfies both and nothing breaks — but the house pattern is to reuse the one capability seam. Consider consolidating onto `SessionProvider` (or a shared `repositories`-level protocol) in a later cleanup so a third off-request agent does not spawn a third copy. Logged, not gated.
- The single-source-of-truth `SECTION_HEADINGS` driving both the tool schema properties and `to_markdown()` is the right call — the section set cannot drift between the LLM contract and the rendered document.
- `career_goal`/`target_date` correctly kept as `generate_pdp` inputs (separate `pdps` columns, owned by P7-03), not folded into `PdpContent` — matches the §4 data split.

## Verdict: APPROVED
