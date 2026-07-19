# Architecture review — P9-06-responder-tone-adaptation · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Prompt-assembly change lives in `agents/` responder | Change confined to `backend/app/agents/responder.py` (+ its test); no other module touched | none |
| A2 | §5.4 loop step 2 "Respond adapted to that context" | Responder consumes `state.memory` to adapt tone/depth/style | `_build_messages` → `_personalization_note(state)` injects one system turn from `preferences` + `memories` | none |
| A3 | §5.4 "Explicit preferences … Authoritative; always injected" + point 4 "explicit edits override inferred memories" | Explicit prefs framed authoritative and overriding at generation time | Preferences line labelled "authoritative … the explicit preference wins"; memories line "inferred — lower priority"; explicit block ordered first | none — precedence made textual, complements P9-05 CRUD-level override |
| A4 | §7.3 trust boundary | prefs/memories are first-party (user-set / P9-04 PII-gated) → NOT fenced as untrusted | Injected as plain persona system turn; `fence_untrusted` correctly reserved for `_grounding_block` worker/crawled content | none — matches task note + [[untrusted-content-contract]] |
| A5 | No-regression (P1/P4 walking-skeleton) | Empty memory ⇒ prompt byte-for-byte unchanged | `_personalization_note` returns `None` when both empty → no block appended; guest gets default-empty `MemoryContext` from P9-02 recall | none |
| A6 | Scope / phase fit | Prompt-assembly only, one synthesis call, both `synthesize()` + `stream()` | Both paths share `_build_messages`; no new LLM call, no DB access, no recall/learn/CRUD change, no frontend | none |
| A7 | §3 single-writer state | Responder reads `state.memory`; memory populated upstream by P9-02 recall node (single writer, no reducer) | Read-only consumption of `MemoryContext.preferences`/`.memories`; shape matches `memory_agent.recall` output | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — agent-node prompt assembly, no cross-layer leak (no DB/driver, no service touch)
- [x] Honors locked decisions — LangGraph node, no ReAct parser, no new datastore, single synthesis call preserved
- [x] Interfaces-before-implementations — consumes `LLMResponder` Protocol + typed `MemoryContext`; no new seam needed
- [x] Budget posture — no new LLM call, no new dependency (free/OSS unchanged)
- [x] DRY/KISS — mirrors planner's `_memory_note` empty-guard idiom; permissive `_render_pref_value` avoids schema coupling to user-controlled JSONB

## Notes
- Precedence is stated in the prompt but ultimately enforced by the model — acceptable and by design; the authoritative CRUD-level override lives in P9-05 ([[pattern-memory-crud-panel]]), and this generation-time framing is the natural complement §5.4 point 4 calls for. No blocker.
- `_render_pref_value` flattening nested maps/lists keeps the prompt robust to any §5.4 prefs shape (tone/formality/language/focus/do-don't) without over-fitting — good posture for when P9-05 PUT writes richer prefs objects.
- Design ruling recorded to memory for consistency across P9 responder/personalization work.
