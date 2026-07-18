---
name: pattern-pdp-agent
description: P7-01 blessed PDP agent — structured PdpContent, deterministic headings, skill-keyed grounding; logged ResourceLookup-vs-SessionProvider DRY dup
metadata:
  type: project
---

P7-01 PDP agent (`agents/pdp_agent.py` + `schemas/pdp.py`) APPROVED rev 1.

**Blessed pattern (for P7-02/03 and future off-request agents):**
- Structured output = forced `record_pdp` tool call carrying six section *bodies* only; canonical `## <Heading>` markers added deterministically by `PdpContent.to_markdown()` (never the model). This is the strongest form of "no ReAct scaffolding can leak" — mirrors planner `record_plan` / market `record_requirements`. `SECTION_HEADINGS` is single-source-of-truth for both the tool schema properties and `to_markdown()` (no drift between LLM contract and rendered doc).
- Grounding: gap from `SkillsGapResult.gap` (ranked), training resources from P6-06 skill-keyed `list_resources_for_skill` (NOT a second similarity search — no embedder, keeps agent off the ML stack), carried structurally in `PdpContent.resources` deduped by URL. "Grounded not hallucinated" (§5.7).
- Graceful degradation via a `status` Literal (profile_missing / role_profile_missing / ok); never raises — caller (P7-03) branches on status. Matches the `SkillsGapResult.status` precedent.
- `career_goal`/`target_date` are `generate_pdp` inputs, NOT `PdpContent` fields — they are separate `pdps` columns owned by P7-03 (§4 split). `pdps` schema untouched.

**Why:** locked §6 native-tool-calling (no ReAct parser) + §7.3 untrusted fencing + §5.1 degradation.
**How to apply:** hold future PDP tasks to this; deterministic-heading + structured-resource shape must survive into the P7-02 PDF builder.

**Logged DRY follow-up (minor, not gated):** `ResourceLookup` Protocol in pdp_agent.py is byte-for-byte identical to `agents/rag_agent.py::SessionProvider` (which market_agent reuses by import). Both structural, same provider satisfies both. House pattern is to reuse the one capability seam — flag consolidation if a third off-request agent copies it again. See [[pattern-market-intel-read-vs-mine-split]].
