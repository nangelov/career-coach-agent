# Engineer report — P7-05-verify · Revision 1

## Summary
Verified the **full P7 exit criterion** end-to-end — *"PDP PDF matches/exceeds v1 quality,
grounded in the user's stored profile."* P7-01 (`pdp_agent.py`), P7-02 (`pdf/builder.py` +
validation gate) and P7-03 (`POST /api/pdp` + `PdpService`) each proved a piece in isolation
(agent / renderer / policy loop / router-over-a-*fake*-service), but **no single test composed
the whole chain**: a stored profile → mined skills gap → corpus resource lookup → `generate_pdp`
→ `validate_pdp_content` → `build_pdp_pdf` → `PdpService` → the real `POST /api/pdp` router.

Added one cohesive verification-only module — `backend/tests/test_p7_exit_verification.py`
(10 tests, mirroring `test_p6_exit_verification.py`) — that drives the **real** PDP chain,
faking only the true external edges (LLM completions, DB sessions), per the P4-10/P5-08/P6-09
posture ("real stack, in-memory/fake ports, no live HF/live Postgres").

**Conclusion: the current P7 implementation MEETS the exit criterion as written.** All 5 task
points are covered (table below). **No gaps** found in P7-01..04 that break the criterion; the
P7-03 rev-2 LLM-outage fix is intact and is now additionally covered by a composed end-to-end
test. The only change beyond the new test was trivial `ruff format` cleanup of three
already-committed-to-disk P7 files (whitespace/line-reflow only — see Files changed).

## Files changed
- `backend/tests/test_p7_exit_verification.py` — **new.** The composed P7 exit verification
  (10 tests). **No product code changed.**
- `backend/app/agents/pdp_agent.py`, `backend/app/pdf/builder.py`,
  `backend/tests/test_pdp_agent.py` — **`ruff format` only** (line-length reflow of three
  f-strings / a signature / a call). Zero logic change; needed so `ruff format --check .` is
  clean for the P7-06 pre-check (these P7-01/02 files had pre-existing format drift). Verified
  cosmetic via `ruff format --diff` before applying.

## Key decisions
- **Compose the real chain; fake only external edges** (P6-09 precedent). The agent runs its
  real fence + forced-`record_pdp` tool-choice + parse path over a scripted `LLMCompleter`; the
  gap runs the real `SkillsGapService`/`compute_skills_gap` over a scripted role-profile session;
  the resource lookup runs the real `list_resources_for_skill` read path over a scripted session;
  the endpoint runs the real `PdpService` + router. Faked: the model, and the DB sessions.
- **Grounding is proven at the structured level, not by grepping the (zlib-compressed) PDF.**
  Point 2 asserts (a) the ranked gap skills reached the model's fenced prompt in descending-
  frequency order, and (b) `PdpContent.resources` are *exactly* the corpus docs the lookup
  returned, deduped by URL (a course surfaced by two gap skills is cited once, carrying both) —
  deterministically injected by the agent, never invented by the model. The PDF itself is
  asserted valid (`%PDF` magic, non-trivial size).
- **"Quality vs v1" is a concrete gate, not prose.** I transcribed v1's `validate_pdp_response`
  contract (six sections, ≥500 chars, no `Action:`/```` ```python ````/`SyntaxError` scaffolding —
  cited to `legacy-code/output_parser.py:368`) rather than importing it (its LangChain imports
  are absent in v2), and assert the v2 rendered markdown **passes the v1 gate**. Plus: the four
  v1 reportlab styling tiers (title/heading/subheading/body) are unchanged, and the v2 cited-
  resource block (which v1 lacked) renders a strictly larger PDF — meets *and* exceeds v1.
- **Degraded paths driven through the real service** (not a `FakePdpService`): missing profile →
  422 + no LLM call + no row; unmined role → 200 best-effort PDF + `X-PDP-Status:
  role_profile_missing`; LLM outage → 502 + no row (the P7-03 rev-2 fix — the honest placeholder
  that passes the length gate must never surface as a 200 PDF; asserted 2 attempts, no persisted
  row). Matches my memory rule [[project-fail-soft-must-be-distinguishable]].
- **Round-trip byte-fidelity** (point 5): a capturing wrapper around the real service records the
  `PdpGenerated.pdf`; the test asserts the HTTP body is byte-identical (reportlab PDFs embed
  timestamps/ids so a re-build would differ — capturing the actual returned bytes is the correct
  no-corruption proof), `application/pdf`, `PDP_Data-Scientist.pdf`.
- **No live-Postgres test needed here.** The task's point-2 direction is explicitly "fakes only at
  the true external edges (LLM, DB)"; unlike P6-09 (whose mining/ranking arithmetic runs *in*
  Postgres/JSONB), the PDP chain's only DB touch is a role-profile read and a skill-keyed resource
  read — both already proven against live Postgres by P6-09's suite. Faking the sessions here
  keeps the P7 chain (agent → gate → builder → service → router) as the unit under test.

## P7 exit criterion — point-by-point
| # | Task point | Where proven |
|---|-----------|--------------|
| 1 | section-header contract in **one place** (`SECTION_HEADINGS`) | `test_section_headings_single_source_in_schema` (all six live in `schemas/pdp.py`, v1 order) + `test_section_headings_not_re_hardcoded_in_agent_or_builder` (agent + builder reference the symbol; <6 literal headings each → no second copy). Confirmed no prompt file hardcodes them. |
| 2 | end-to-end → **valid, styled, grounded** PDF | `test_end_to_end_generation_produces_grounded_styled_pdf` (real generate→validate→render; `%PDF` + >1500 bytes; ranked gap reached the fenced prompt; cited resources == corpus docs, deduped) |
| 3 | **quality vs v1** (meets + exceeds) | `test_rendered_plan_meets_v1_contract` (v2 markdown passes the transcribed v1 gate) + `test_pdf_carries_v1_styling_tiers_and_v2_additions` (same 4 tiers + larger PDF from the v2 cited-resource block) + `test_pdp_tool_schema_is_the_forced_six_section_contract` (native tool-call ⇒ ReAct scaffolding structurally impossible) |
| 4 | degraded paths don't regress | `test_missing_profile_is_422_no_pdf_no_row`, `test_unmined_role_best_effort_pdf_with_status_header`, `test_llm_outage_is_502_no_row_no_placeholder_pdf` (P7-03 rev-2 fix intact) — all via the **real** service through the endpoint |
| 5 | `POST /api/pdp` **download round trip** | `test_download_round_trip_bytes_uncorrupted` (body byte-identical to the builder's output; `application/pdf`; `PDP_<goal>.pdf`; one persisted row) |

## Gaps flagged in prior P7 tasks
**None.** All P7-01..04 behaviours needed by the exit criterion hold. The P7-03 rev-2 fix
(LLM-outage → `generation_failed` → 502, no row) is present and now has composed coverage. The
only issue encountered was cosmetic `ruff format` drift in P7-01/02 files, fixed in place (in
scope for a phase-exit green-check, mirroring P6-09) rather than routed back.

## How to verify
```bash
# Backend (from backend/) — mirrors `make check`:
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy app/ migrations/
.venv/bin/python -m pytest -q                      # offline (59 live-DB tests skip)
# Focused:
.venv/bin/python -m pytest tests/test_p7_exit_verification.py -q
```

## Tests (final step — mandatory)
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → **216 files already formatted** (3 P7 drift files fixed).
- `mypy app/ migrations/` (CI scope) → **Success: no issues found in 130 source files**;
  `mypy tests/test_p7_exit_verification.py` → **Success: no issues found**.
- `pytest -q` (offline) → **653 passed, 59 skipped** (+10 new; the 59 skips are the pre-existing
  live-DB `*_postgres` integration tests — no Postgres in this run, unrelated to this task).
- Focused: `pytest tests/test_p7_exit_verification.py -q` → **10 passed**.
- No failing tests. No test weakened or deleted; no product code logic changed.

## Self-check
- [x] Meets acceptance criteria — all 5 P7-05 points covered by composed/integration-level
  tests; the one live-infra choice (no live Postgres) is documented above; `ruff check` +
  `ruff format --check` + `mypy` (app+migrations) + `pytest` all green; report states the
  criterion **is met** and confirms no P7-01..04 gap.
- [x] No secrets committed; verification-only (no product-code logic changed); Router→Service→
  Agent/Repo layering respected (the tests drive the real layered stack, faking only the LLM +
  DB edges).
- [x] Tests/lints pass (results pasted above).
