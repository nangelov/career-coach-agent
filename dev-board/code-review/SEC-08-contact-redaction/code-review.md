# Code review — SEC-08-contact-redaction · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/llm/redaction.py:77-81 | Blanket URL redaction also strips URLs from `role="tool"` messages (web-search / job-search results flowing back to the responder), so the coach can never surface a job-posting or source link. This is the task-sanctioned "blanket at the router" default and documented as safe-direction over-redaction, but it plausibly "visibly breaks a normal chat flow" (job links) the task flagged as a deviation trigger. | No change required to pass; confirm with system-architect whether the job/source-link UX is acceptable or warrants scoping URL redaction to CV-origin content only. Follow-up, not a gate. |
| C2 | nit | backend/app/llm/redaction.py:125-139 | Header-name heuristic redacts any first line that is exactly 2-3 capitalized words, so a benign chat opener like "Thank You" / "Good Morning" becomes `[NAME REDACTED]` on the hot path. | Accept as documented best-effort; optionally require ≥1 non-dictionary token or a following contact block before treating the header as a name. Non-blocking. |
| C3 | nit | backend/app/llm/redaction.py:106-111,87-99 | Best-effort address/phone patterns over-match rare CV substance (`5 Sales Drive` → address; `100 000 5000` → phone). | None — matches the documented best-effort posture and fail-safe (over-redaction) direction. |

## Notes
- **Chokepoint verified.** `redact_messages` is called at the top of both `LLMRouter.complete` (router.py:230) and `LLMRouter.stream` (router.py:310), before the client loop. Integration tests (`test_complete_redacts_before_client_call`, `test_stream_redacts_before_client_call`) assert on the messages a `_RecordingClient` actually received — not the utility in isolation — satisfying the task's core requirement.
- **No duplication.** Grepped `backend/app` for `redact`: only the utility, the router wiring, and its exports. Nothing scattered into `structuring.py` / `responder.py` / `planner.py` / `tools/`.
- **CV substance preserved.** "Senior Engineer at Acme Corp, 2019-2023", skills, and education lines pass through unchanged (verified by test + manual run); the conservative two-separator phone regex correctly leaves `2015-2019` / `2019-2023` date ranges intact.
- **Security posture is fail-safe.** All deviations lean toward *more* redaction (over-redact), which is the correct direction at a PII egress boundary. `content`-only scope leaves `tool_calls`/metadata untouched (documented, out of scope). Mid-stream resume prefill is model-generated from already-redacted input and correctly not re-redacted; unchanged messages returned by identity (cheap hot path).
- **Scope boundaries honored.** Embeddings pipeline deliberately untouched (noted as follow-up); photo/image N/A documented; limitations docstring mirrors the `guardrails/heuristics.py` honesty convention.
- **Tests/verification run locally.** `pytest tests/test_llm_redaction.py` → 14 passed in the backend `.venv`. Edge cases exercised manually (see findings).
- All five acceptance criteria are met. C1 is a design-scoping question I'm deferring to the system-architect (it is the task's own sanctioned default); C2/C3 are documented best-effort tradeoffs. None rise to blocker/major.
