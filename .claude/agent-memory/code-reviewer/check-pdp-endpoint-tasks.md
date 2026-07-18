---
name: check-pdp-endpoint-tasks
description: Reviewing P7-03+ PDP endpoint/service tasks (api/pdp.py, services/pdp.py) — the agent-fallback-defeats-validation-gate trap
metadata:
  type: project
---

Reviewing the PDP endpoint (P7-03: `api/pdp.py` router → `services/pdp.py` `PdpService` →
`agents/pdp_agent.py::generate_pdp` → `pdf/builder.py::validate_pdp_content`/`build_pdp_pdf` →
`repositories/pdp_store.py`).

**Why:** The P7 stack promises "validate gates every PDF; a validation failure is retried once
then a clear 502 error, never a broken PDF" (mirrors v1 semantics). The trap: `generate_pdp`
**swallows `LLMError`/unusable tool calls and returns `_fallback_sections()`** — six identical
"We could not generate this section…" placeholders (~89 chars × 6 = 534 chars) with `status`
left at `"ok"`/`"role_profile_missing"`. That fallback **passes `validate_pdp_content`**
(MIN_PDP_CHARS=500, MIN_REQUIRED_SECTIONS=4), so on a real LLM outage the service returns a 200
PDF of placeholders, charges the message budget, and persists a garbage `pdps` row that P8
dashboard-seeding will read. The `PdpGenerationFailed`→502 retry path is unreachable for the
most likely failure mode. Flagged as **major** in rev 1.

**How to apply:** Whenever a service layers a validation-gate/retry safety net on top of an agent
that degrades gracefully with *substantial-looking* placeholder text, check whether the fallback
passes the gate — if it does, the gate/retry is defeated and failures are masked. The agent must
signal failure explicitly (a distinct `PdpStatus`/return) for the service to map it to an error.
Also check: rate-limit charged before a no-op 422 (no-profile) path; redundant profile fetch
(`PdpService.generate` + `SkillsGapService.compute` both call `profile_store.get`); and require a
service-level test that drives the completer to *raise* `LLMError` (the fakes usually only script
successful tool calls, so this path goes untested). See [[check-langgraph-state-tasks]] for other
agent-seam gotchas.
