# Task P7-05-verify — P7 exit: PDP PDF quality vs v1; headers stay in sync

- **Phase:** P7   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: *"PDP PDF quality vs v1; section headers stay in sync with prompt + PDF
builder."*

This is the phase-level integration verification pulling together P7-01 (`pdp_agent.py`),
P7-02 (`pdf/` builder + validation gate) and P7-03 (`POST /api/pdp`). Mirror how
`P6-09-manual-verify` composed its phase-exit verification (read
`dev-board/code-review/P6-09-manual-verify/task.md` + `engineer.md` for the expected
shape/rigor) — don't just re-run each prior task's own suite in isolation; prove the **whole
chain** end-to-end and report a clear yes/no on the P7 exit criterion ("PDP PDF matches/
exceeds v1 quality, grounded in the user's stored profile").

Specifically verify:

1. **Section-header contract stays in one place.** `app.schemas.pdp.SECTION_HEADINGS` (P7-01)
   is the *only* source of truth for the six v1 headings (`Current Skills Assessment`,
   `Skills Gap Analysis`, `Learning Objectives and Milestones`, `Recommended Training and
   Development`, `Timeline and Action Steps`, `Progress Tracking and KPIs`). Grep
   `app/agents/pdp_agent.py`, `app/pdf/builder.py` and any prompt text to confirm none of them
   hardcode a second copy of this list — if one is found, that's a gap to flag (or fix, if
   trivial) precisely which file.
2. **End-to-end generation → valid, styled PDF**, composed with fakes only at the true
   external edges (LLM completions, DB) — mirroring the P4-10/P6-09 precedent ("real stack,
   in-memory/fake ports, no live HF/live Postgres"): a fixture structured profile + a fixture
   `role_profile`/skills-gap result run through `generate_pdp` → `validate_pdp_content` →
   `build_pdp_pdf` produces PDF bytes that (a) start with the `%PDF` magic, (b) are non-trivial
   in size, (c) are grounded — the skills-gap items and cited learning resources that went in
   are traceable in the structured `PdpContent` that came out (not just "some PDF was
   produced").
3. **Quality vs v1** — a documented, side-by-side comparison against the v1 contract
   (`legacy-code/helpers/helper.py` + `legacy-code/output_parser.py::validate_pdp_response`):
   same six sections, same styling tiers (title/heading/subheading/body), **plus** v2
   additions v1 lacked (cited learning resources, grounded skills-gap ranking, no ReAct
   scaffolding ever possible per P7-01's forced-tool-call design). State plainly whether v2
   meets or exceeds v1 on this basis.
4. **Degraded paths don't silently regress quality**: missing profile (422, no PDF), unmined
   role (best-effort PDF + `X-PDP-Status` header, not a crash), and validation-retry-exhausted
   (502, no row persisted) each behave as P7-03 designed and documented — spot check these are
   still true after P7-01..04, since revisions happened along the way (P7-03 had a rev-2 fix
   for the LLM-outage-fallback bug — confirm that fix is still intact and covered by a test).
5. **`POST /api/pdp` → download round trip**: an API-level test (FastAPI test client, fake
   service/agent seams per P7-03's existing test style) confirms the endpoint returns
   `application/pdf` with a sane filename and the PDF bytes are exactly what the service/
   builder produced (no corruption through the response path).

## Acceptance criteria
- [ ] All 5 points above are covered by automated tests (composed/integration-level where
      prior per-task tests only proved pieces in isolation) or a clearly documented reason
      something requires live infra this environment doesn't have.
- [ ] Full backend test suite green (`ruff check`, `ruff format --check`, `mypy`, `pytest`) —
      this is a pre-check for P7-06, not a substitute for it, but don't leave it red here.
- [ ] Report states clearly: does the current P7 implementation meet the exit criterion
      ("PDP PDF matches/exceeds v1 quality, grounded in the user's stored profile")? If a gap
      is found in any prior P7 task's work (P7-01/02/03/04), flag it precisely (which task,
      what's missing) rather than silently patching around it, so the orchestrator can route a
      fix to the right task.

## Design references
- `dev-board/plan.md` — Phase 7 exit criterion.
- `dev-board/app-design-and-features.md` §5.2 / §5.6 (PDP grounded in profile + skills gap).
- Precedent: `dev-board/code-review/P6-09-manual-verify/`, `dev-board/code-review/P5-08-verify/`.
- `legacy-code/helpers/helper.py`, `legacy-code/output_parser.py` — the v1 baseline being
  compared against.
