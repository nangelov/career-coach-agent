# Task P7-02-pdf-builder — reportlab PDF builder ported to `pdf/` + validation gate

- **Phase:** P7   **Status:** ENG   **Tags:** (B)

## Scope
Port the v1 reportlab PDF builder into the v2 `backend/app/pdf/` package (currently only
`__init__.py`), consuming the **structured** `PdpContent` produced by P7-01
(`app.schemas.pdp.PdpContent`, `SECTION_HEADINGS`, `.to_markdown()`) instead of a raw LLM
string, and port the pre-render validation gate.

Reference v1 (legacy, not on the runtime path):
- `legacy-code/helpers/helper.py` — `create_pdp_pdf`, `prepare_pdf_content` (markdown→reportlab
  line-by-line conversion, styles: title/heading/subheading/body).
- `legacy-code/output_parser.py::validate_pdp_response` — the pre-render gate: reject if
  `len(text) < 500` or fewer than 4 of the 6 required section headings are found
  (case-insensitive substring match on the six heading names).

What to build in `backend/app/pdf/`:
- A `build_pdp_pdf(content: PdpContent, career_goal: str, target_date: str | None) -> bytes`
  (or `BytesIO`) function/module that renders the same styled PDF v1 produced (title,
  career-goal/target-date/generated-on header, per-section reportlab styles) — but driven by
  `PdpContent`'s six typed fields (+ `resources` citations) rather than re-parsing markdown
  line-by-line. You may still use `PdpContent.to_markdown()` internally if that's the
  cleanest way to reuse the v1 heading/body/bullet rendering logic — your call, but the
  section-header contract (`SECTION_HEADINGS` from P7-01) must stay the single source of
  truth, not a second hardcoded list.
- A `validate_pdp_content(content: PdpContent) -> bool` (or equivalent) gate: keep the v1
  rule (≥500 chars across sections, ≥4/6 required headings present with non-trivial body) —
  reusing `SECTION_HEADINGS` from `app.schemas.pdp`, not a re-typed copy. This is the
  pre-render check P7-03's endpoint calls before returning a PDF; on failure the endpoint
  should get a clear signal to retry/error rather than silently emitting a broken PDF.
- Render `PdpContent.resources` (cited learning resources from P7-01) as a visible section
  (e.g. under/near "Recommended Training and Development") — title, provider, URL — so the
  citation requirement (§5.7, "grounded, not hallucinated") is visible in the output PDF, not
  just in JSON.
- Unit tests: validation gate (pass/fail cases — short content, missing headings), and a
  render smoke test (builds valid, non-empty PDF bytes from a representative `PdpContent`,
  including with/without resources, without needing to visually inspect the PDF — e.g. assert
  it starts with the PDF magic bytes `%PDF` and reportlab doesn't raise).

## Acceptance criteria
- [ ] `backend/app/pdf/` exposes a PDF-builder function consuming `PdpContent` (P7-01) and a
      validation gate reusing `SECTION_HEADINGS` (no duplicated heading list).
- [ ] Output PDF includes: title, career goal, target date, generated-on date, all six
      sections with v1-equivalent styling, and cited learning resources.
- [ ] Validation gate matches v1 semantics (≥500 chars, ≥4/6 headings) operating on the
      structured `PdpContent`, not a raw string re-parse.
- [ ] Unit tests cover validation pass/fail and PDF render smoke test.

## Design references
- `dev-board/plan.md` — Phase 7 ("Keep reportlab builder ... keep section-header contract and
  validation gate").
- `dev-board/tasks.md` — P7 item: "Port `helpers/helper.py` reportlab builder → `pdf/`; keep
  section-header contract + `validate_pdp_response` gate."
- `dev-board/code-review/P7-01-pdp-agent/engineer.md` — the `PdpContent` shape you consume.

## Constraints / non-goals
- Do not implement `/api/pdp` (P7-03) or the frontend (P7-04) — this task is the `pdf/`
  module + its tests only. P7-03 will call your builder + gate.
- Don't change `app/schemas/pdp.py` beyond what's strictly needed (e.g. if you find a genuine
  gap, flag it in the report rather than reshaping P7-01's contract unilaterally).
