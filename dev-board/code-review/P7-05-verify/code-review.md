# Code review — P7-05-verify · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/tests/test_p7_exit_verification.py:250-262 | `test_section_headings_not_re_hardcoded_in_agent_or_builder` gates on `present < 6`, so a *partial* second copy (e.g. 5 of 6 headings pasted into the agent/builder) would still pass. The intent (no full duplicate) is met today, but the heuristic is looser than "no heading beyond the one allowed prose mention." | No change required for this task; if tightened later, count occurrences per heading rather than distinct headings present. |
| C2 | nit | backend/tests/test_p7_exit_verification.py:268-339 | Point-2 gap grounding is proven only at the *prompt* level (ranked gap reached the fenced system message in descending order); it is not traceable in a structured `PdpContent` field (the `skills_gap_analysis` body is free model text). Resources ARE traceable structurally. This matches the design (gap drives the prompt, resources are the structured citation) and is documented honestly in the report — noted so the conclusion isn't over-read. | None. |

## Notes
- **Verification-only, no product logic changed.** The sole deliverable is
  `backend/tests/test_p7_exit_verification.py` (10 tests). The three files the report calls
  "`ruff format` only" (`app/agents/pdp_agent.py`, `app/pdf/builder.py`, `tests/test_pdp_agent.py`)
  are **untracked** new files from P7-01/02 not yet committed, so there is no committed-logic
  regression risk; `ruff format --check .` is green. Reformatting sibling-task files for a
  phase-exit green-check follows the P6-09 precedent — in scope, not a gate issue.
- **All four gates reproduced exactly:** `ruff check .` → all passed; `ruff format --check .` →
  216 files already formatted; `mypy app/ migrations/` → no issues in 130 files, `mypy` on the
  new test → clean; `pytest -q` → **653 passed, 59 skipped**; focused module → **10 passed**.
  The 59 skips are the pre-existing live-Postgres `*_postgres` integration tests (no DB in this
  run), unrelated to this task.
- **Tests are genuinely discriminating, not always-green:**
  - Point 1 asserts the six headings live only in `schemas/pdp.py` (v1 order) and that agent +
    builder derive from `SECTION_HEADINGS` — confirmed in source: both iterate the symbol, neither
    hardcodes the list, and no separate prompt file exists (the system prompt is inline in
    `pdp_agent.py`, which is scanned).
  - Point 2 runs the **real** `generate_pdp` → real `SkillsGapService.compute_skills_gap` → real
    `_lookup_resources`/`_merge_resource` dedup, and asserts descending-frequency ordering in the
    fenced prompt plus URL-deduped resources carrying both matched skills (`ex.com/c` → `[Kubernetes,
    SQL]`). Not a "some PDF was produced" test.
  - Point 4's `test_llm_outage_is_502_no_row_no_placeholder_pdf` drives a `_RaisingCompleter`
    through the **real** `PdpService` and asserts `502`, `store.saved == []`, and `completer.calls
    == 2` — this is exactly the P7-03 rev-2 trap (the `_fallback_sections` placeholder passes the
    length gate; `generation_failed` status must map to 502, never a 200 PDF or persisted row). I
    verified the fix is intact: `pdp_agent._degraded_generation_failed` sets
    `status="generation_failed"`, `PdpService.generate` rejects it before `validate_pdp_content`
    and returns `PdpGenerationFailed`, and `api/pdp.py` maps that to 502. This matches the gotcha in
    my `check-pdp-endpoint-tasks` memory and is now covered end-to-end.
  - Point 5 uses a capturing wrapper to assert the HTTP body is byte-identical to the builder's
    output (correct proof — reportlab embeds timestamps, so a re-build would differ), plus
    `application/pdf`, `PDP_Data-Scientist.pdf`, `X-PDP-Status`, and exactly one persisted row.
- **No gaps found in P7-01..04** that break the exit criterion; the report's "None" conclusion is
  accurate. The `< 6` heuristic (C1) and prompt-level gap grounding (C2) are nits, not defects.
- **Exit criterion met:** the P7 chain (agent → validation gate → builder → service → router)
  composes and is proven end-to-end with fakes only at the LLM + DB edges, matching the
  P4-10/P5-08/P6-09 posture; degraded paths (422 / best-effort 200 / 502) behave as designed.
