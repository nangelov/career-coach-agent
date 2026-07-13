# Code review — SEC-02-untrusted-content-contract · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/guardrails/untrusted_content.py:68-81 | Fence markers (`--- BEGIN/END <LABEL> ---`) are fixed, guessable strings and untrusted `blocks` are spliced in verbatim with no sanitisation. An adversarial CV/crawled page containing the literal `--- END CV CONTENT ---` (or `--- END REFERENCE MATERIAL ---`) can close the fence early and present following text as out-of-fence "trusted" prose — a delimiter-injection breakout of the very structural contract §7.3 asks for. Matches the pre-existing responder precedent, so not a regression, and P10 owns the real classifier — hence non-gating. | Cheap defence-in-depth: before fencing, neutralise/escape any occurrence of the `--- END <MARKER> ---` (and ideally `--- BEGIN`) token inside each block (e.g. zero-width break or replace). Apply in the shared helper so both callers benefit. |
| C2 | nit | backend/app/services/chat.py:319 | Per-chunk `screen_output` cannot catch an injection phrase whose tokens straddle two `StreamChunk`s, so the streamed answer *and* the `parts`-assembled persisted `response` stay weaker than the buffered `output_guardrail_node` path (which sees the whole string). Already documented in the docstring and deferred to P10. | None required; accept as documented limitation. Optionally re-screen the fully assembled `parts` once at stream end for defence-in-depth. |
| C3 | nit | backend/app/agents/graph.py:157 | On the streaming path `output_guardrail_node` never runs, so no OUTPUT `SafetyVerdict` is stamped onto `AgentState.output_safety` for streamed turns (telemetry gap vs. buffered path). | None required; note for P10 when the streaming/verdict story is unified. |

## Notes
- Acceptance criteria all met: single shared `fence_untrusted` used by both `responder._grounding_block` and `structuring._build_messages` (DRY, no forked fence); CV/OCR text now fenced + labelled as data; `screen_output` reuses the one `_DENY_PATTERNS` deny-list (no second copy) and is wired into both the buffered node and the streaming service; audit written; tests cover CV-injection-ignored, crawled-page fenced, and echoed-phrase strip.
- **Tool-call audit independently verified.** Grepped `tools=`/`tool_choice=` completion sites: only `planner.py` (forced `PLANNER_TOOL_SCHEMA`) and `structuring.py` (forced `PROFILE_TOOL_SCHEMA`); `responder.py` has none. Both tool sites are single forced schemas that cannot expand scope; the planner receives no untrusted external text; the structurer's CV text is now fenced. Audit conclusion "no gap" is accurate.
- Import-cycle fix (lazy `agents.state` import inside the screen functions + `TYPE_CHECKING`) correctly keeps `guardrails` a lower layer than `agents`; layering respected.
- Scrub-neutralises-not-blocks posture (verdict stays `allowed=True`, fragment → visible `[removed]`) is auditable and avoids splicing unrelated clauses — good call.
- Verified locally: `pytest tests/test_untrusted_content.py -q` → 10 passed; `ruff` on all changed files → clean; `mypy` on the 6 changed source files → clean.
- The `web_searcher.py` / `fakes.py` diffs in the working tree belong to SEC-01 (SSRF guard), not this task — out of scope here, not reviewed against SEC-02.
