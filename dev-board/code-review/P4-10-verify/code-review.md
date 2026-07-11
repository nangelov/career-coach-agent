# Code review — P4-10-verify · engineer revision 1

## Verdict: APPROVED

## Findings

| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/tests/test_p4_exit_verification.py:174,230,269 | `# type: ignore[arg-type]` on the `planner=` seam args works around a loose stub signature rather than typing the seam. | Optional: type the `build_graph(planner=...)` seam as a `Callable[[AgentState], dict[str, object]]` so the ignores can drop. Non-blocking. |
| C2 | nit | (process) reformat of 5 files | The mechanical `ruff format` fix is bundled into this verification task; 3 are tracked (identity.py, test_feedback_reader.py, test_p3_exit_verification.py), 2 are new/untracked P4 files. | Optional: orchestrator may prefer folding the 3 tracked-file reformats into their originating P4 tasks' commits. Cosmetic only. |

## Notes

Verified the two things this task actually touches (all other P4-01..P4-09 code was reviewed under its own task):

**1. The claimed-mechanical `ruff format` reformat is genuinely zero-logic-change.**
Inspected the diff of each of the 3 *tracked* files (`identity.py`, `test_feedback_reader.py`,
`test_p3_exit_verification.py`): every hunk is pure line-collapsing (multi-line call args folded onto one
≤100-col line) — identical identifiers, arguments, and values, no behavior change. The other 2 files
(`planner.py`, `test_agent_planner.py`) are new/untracked P4 files, so reformatting them changes no committed
logic. `ruff format --check .` → **126 files already formatted** (gate now green). Confirmed mechanical as
claimed.

**2. The new verification module is sound and actually proves what it claims.**
`test_p4_exit_verification.py` drives the real compiled `GraphTurnStreamer` + real `ChatService` + real
`POST /api/chat` SSE surface, faking only the outermost edges (responder-LLM router, the P4-03
`build_graph(planner=...)` routing seam, embedder+scripted pgvector, search tool+mock httpx). The streaming
assertion is genuinely discriminating — it requires ≥2 `token` frames that reassemble the full answer AND that
no single frame carries the whole answer (a buffered response would fail), all ordered before the terminal
`done`. Citations are checked real-vs-empty (RAG title / web URL with `worker` tag vs `[]` for smalltalk), the
`plan` event is asserted to match the route that ran, and the blocked-turn test uses the responder as a spy
(`stream_messages == [] and complete_messages == []`) to prove the LLM is never reached — no `plan`, no
`error`. All referenced fakes exist in `tests/fakes.py`.

**Ran every gate myself (matches the engineer's report exactly):**
- `ruff check .` → All checks passed
- `ruff format --check .` → 126 files already formatted
- `mypy app/ migrations/` → Success, no issues in 75 files
- `pytest -q` → **312 passed, 43 skipped**
- `pytest tests/test_p4_exit_verification.py -q` → **4 passed**
- Frontend `npm test` → **6 suites, 59 passed** (covers criterion #7 plan/citation rendering)

Acceptance criteria met: all 7 exit-criterion points are covered by automated tests, both full suites are
green, the live-infra pass is appropriately documented as skipped (needs external creds), and the report
clearly states the implementation meets the full P4 exit criterion with no gap found. Regression criteria (#6)
and frontend (#7) correctly lean on existing suites rather than duplicating coverage (DRY/YAGNI). No blocker or
major issues.
