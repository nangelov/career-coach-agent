---
name: pattern-responder-personalization
description: P9-06 blessed — responder consumes state.memory to adapt tone; trusted-not-fenced injection, textual explicit-over-inferred precedence, empty=no-regression
metadata:
  type: project
---

P9-06 (responder tone adaptation) APPROVED rev 1. Blessed the §5.4 loop step 2 ("Respond adapted to that context") wiring in `backend/app/agents/responder.py`.

**Why:** design §5.4 requires the responder to adapt tone/depth/style to recalled prefs/memories, with explicit prefs authoritative and overriding inferred memories (point 4).

**How to apply (rulings for future P9 responder/personalization work):**
- Personalization = **trusted persona system turn, NOT fenced**. prefs/memories are first-party (user-set / P9-04 PII-gated), so `fence_untrusted` stays reserved for worker/crawled grounding only ([[project-untrusted-content-contract]]). Do not re-litigate.
- **Explicit-over-inferred precedence must be textual** in the prompt (preferences labelled authoritative/overriding, memories labelled inferred/lower-priority, explicit block ordered first). Model-enforced framing is accepted as the generation-time complement to P9-05's CRUD-level override ([[pattern-memory-crud-panel]]).
- **Empty memory ⇒ byte-for-byte unchanged prompt** (return None from the note builder, mirror planner's `_memory_note` empty-guard idiom). No empty block, no walking-skeleton regression.
- Prompt-assembly only: one synthesis call, both `synthesize()` + `stream()` share `_build_messages`, no DB/new-LLM-call/frontend change. Consumes `MemoryContext` populated by P9-02 recall ([[pattern-memory-recall-store]]).
- Permissive `_render_pref_value` (flatten scalar/list/nested-map, drop empties) avoids schema coupling to the user-controlled `preferences` JSONB — good KISS posture.
