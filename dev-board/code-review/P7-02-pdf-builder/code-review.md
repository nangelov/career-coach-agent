# Code review — P7-02-pdf-builder · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/pdf/builder.py:175-178 | The numbered-list branch (`re.match(r"^\d+\."...)`) produces exactly the same output as the `else` branch (`_inline(line)`); it documents intent but is dead branching. | Optional: collapse into the `else`, or leave with a comment. Faithful to v1's structure, so not blocking. |
| C2 | nit | backend/app/pdf/builder.py:81 | `story: list[object]` is looser than the reportlab flowable type. | Optional: `list[Flowable]`; `object` is fine for mypy-strict and matches KISS. |

## Notes
- **Correctness / port fidelity:** Styling (title/heading/subheading/body colours, font sizes, indents, A4 margins, spacers) matches v1 `create_pdp_pdf` exactly. Inline handling ports v1 `prepare_pdf_content` and is strictly more robust — the `_inline` while-loop handles multiple `**` spans (v1 only converted the first pair) and bullets-containing-bold now convert correctly (v1's `**`-before-bullet elif ordering mis-handled that). No regressions found.
- **Security:** XML-escape runs *before* any `<b>`/bullet markup is injected on every path (`_inline`, `_resource_line`, career_goal, target_date, headings, resource url/provider). Verified hostile input (`<`, `&`, unbalanced `**`, literal `<b>`) renders without breaking the reportlab paragraph parser and cannot inject markup. No untrusted-code execution, no secrets, pure rendering module (no DB/service calls) — layering respected.
- **Single source of truth:** Both functions iterate `SECTION_HEADINGS` from `app.schemas.pdp`; no second hardcoded heading list. Acceptance #1 met.
- **Resources:** Confirmed rendered as a visible "Cited Learning Resources" list under *Recommended Training* (§5.7), including when the section body is empty but resources exist (manually verified — valid PDF, 2342 bytes).
- **Gate semantics:** `validate_pdp_content` keeps ≥500 chars + ≥4/6 sections, reinterpreting v1's substring-heading count as "≥4 sections with a non-trivial (post-trim) body" — reasonable given headings are now deterministic (`to_markdown` adds them). Documented in constants/docstrings. Whether this structural analogue satisfies the design intent is the system-architect's call; it is faithful and defensible from a correctness view.
- **Tests:** `pytest tests/test_pdf_builder.py -q` → 11 passed. `ruff check` clean. `mypy app/pdf/` (strict) clean. Tests cover gate pass/fail (short, too-few-sections, exactly-4 boundary, whitespace-only) and render smoke (valid bytes, no target date, with/without resources, hostile markup) plus the `_inline` helper. Coverage is adequate for the module.
- Only `nit`-level findings — no blocker/major/minor. Approving.
