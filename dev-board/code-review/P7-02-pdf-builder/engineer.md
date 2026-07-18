# Engineer report — P7-02-pdf-builder · Revision 1

## Summary
Ported the v1 reportlab PDP builder into `backend/app/pdf/`, driven by the **structured**
`PdpContent` (P7-01) instead of re-parsing a raw LLM markdown blob. Two exports: `build_pdp_pdf`
(styled A4 PDF matching v1's title/header/section styling, with the cited learning resources
rendered as a visible list under *Recommended Training and Development*, §5.7) and
`validate_pdp_content` (the pre-render gate, keeping v1's ≥500 chars + ≥4/6 sections semantics
but over the typed model). Both iterate `SECTION_HEADINGS` from `app.schemas.pdp` — the section
contract stays a single source of truth, never re-typed here.

## Files changed
- `backend/app/pdf/builder.py` (new) — `build_pdp_pdf`, `validate_pdp_content`, the four v1
  paragraph styles, `_body_lines` (inline body markup port), `_inline` (XML-escape + `**`→`<b>`),
  `_resource_line`, and the `MIN_PDP_CHARS`/`MIN_REQUIRED_SECTIONS` gate constants.
- `backend/app/pdf/__init__.py` — export the two functions + the two threshold constants.
- `backend/tests/test_pdf_builder.py` (new) — 11 unit tests: gate pass/fail (short plan, too
  few sections, exactly-4 boundary, whitespace-only bodies), render smoke tests (valid bytes,
  no target date, with/without resources, hostile markup chars), and the `_inline` helper.

## Key decisions
- **Iterate `SECTION_HEADINGS`, don't re-parse `to_markdown()`.** The builder walks the P7-01
  heading tuple directly, emitting each `## <Heading>` in v1's heading style and each field body
  through the ported inline converter. This satisfies the task's "driven by typed fields rather
  than re-parsing markdown line-by-line" and lets the cited resources be injected right after
  the *Recommended Training* body — which re-parsing a flat markdown string couldn't do cleanly.
  No second hardcoded heading list (acceptance #1).
- **Validation gate over the structured model.** `validate_pdp_content` sums the six trimmed
  section bodies for the ≥500-char check and counts non-empty bodies for the ≥4/6 check.
  Headings are now added deterministically by P7-01, so v1's "≥4 of 6 heading substrings present"
  is meaningless on structured input; the faithful structural analogue is "≥4 sections carry a
  non-trivial (non-empty after trim) body". Constants named + documented (acceptance #3).
- **XML-escape before injecting markup.** v1 fed raw LLM text straight into reportlab; `<`, `&`
  in model output would break the paragraph parser. `_inline`/`_resource_line` escape first, then
  inject `<b>` tags (and close a dangling `**`), so hostile/markdown-y bodies render safely.
- **Return `bytes`.** Clean contract for P7-03 (wrap in `BytesIO`/`StreamingResponse`); drops
  v1's unused `filename` param (KISS/YAGNI).
- **No `app/schemas/pdp.py` change needed** — `PdpContent` + `LearningResourceRef` +
  `SECTION_HEADINGS` covered everything; nothing reshaped (task constraint).

## How to verify
```
cd backend && .venv/bin/python -m pytest tests/test_pdf_builder.py -q
.venv/bin/ruff check app/pdf/ tests/test_pdf_builder.py
.venv/bin/mypy app/pdf/
```

## Tests (final step — mandatory)
- `pytest tests/test_pdf_builder.py -q` → **11 passed**.
- `ruff check app/pdf/ tests/test_pdf_builder.py` → All checks passed (fixed one UP017 —
  `datetime.timezone.utc` → `datetime.UTC`).
- `mypy app/pdf/` (strict) → Success, no issues.
- **Full suite:** `pytest -q` → **629 passed, 59 skipped** (skips are the live-DB `*_postgres`
  integration tests — no Postgres in this run; unrelated to this task).
- No code or test defects surfaced; nothing left red.

## Self-check
- [x] Meets acceptance criteria: `build_pdp_pdf(PdpContent, career_goal, target_date)` renders
      title + career goal + target date + generated-on + all six v1-styled sections + cited
      resources; `validate_pdp_content` keeps v1 semantics over the typed model reusing
      `SECTION_HEADINGS`; tests cover gate pass/fail + render smoke (with/without resources).
- [x] No secrets committed; layering respected (pure rendering module — no DB/driver/service
      calls; consumes the P7-01 schema only).
- [x] Tests/lints pass (results pasted above).

## Notes / flags
- Out of scope, left for their tasks: `/api/pdp` endpoint + composition wiring (P7-03), frontend
  (P7-04). P7-03 calls `validate_pdp_content` then `build_pdp_pdf`.
