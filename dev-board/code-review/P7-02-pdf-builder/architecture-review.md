# Architecture review — P7-02-pdf-builder · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | reportlab builder lives in `app/pdf/` | `backend/app/pdf/builder.py` + `__init__.py` exports `build_pdp_pdf` / `validate_pdp_content` (+ threshold constants). v1 code stays in `legacy-code/` | none |
| A2 | Layering (SoC) | pure rendering module; no DB/driver/service leaks | Consumes only `app.schemas.pdp` (P7-01 contract); no repo/session/LLM imports; returns `bytes` for P7-03 to wrap | none |
| A3 | No ReAct scaffolding (locked v6) | headings deterministic, no text re-parse | Iterates `SECTION_HEADINGS` field-by-field over the typed model; v1's scaffolding-rejection gate is correctly dropped as unreachable (headings added by P7-01, never the model) | none |
| A4 | DRY — single heading SSOT | reuse `SECTION_HEADINGS`, no second list | Both `build_pdp_pdf` and `validate_pdp_content` walk `SECTION_HEADINGS`; no re-typed heading list anywhere | none |
| A5 | §5.7 grounded citations visible | cited resources rendered in PDF, not just JSON | `resources` rendered as a "Cited Learning Resources" list (title / provider / URL) right after the `recommended_training` body via `_RESOURCE_SECTION_FIELD` anchor | none |
| A6 | Validation gate = v1 semantics | ≥500 chars, ≥4/6 sections | `MIN_PDP_CHARS=500`; ≥4/6 reinterpreted as ≥4 sections with a non-trivial (trimmed non-empty) body — the faithful structural analogue now that headings are deterministic. Documented on the constants (see Note) | none |
| A7 | P7-01 contract untouched | don't reshape `schemas/pdp.py` | No schema change; `PdpContent` + `LearningResourceRef` + `SECTION_HEADINGS` covered everything (task constraint honored) | none |
| A8 | Budget posture (§11) | free/OSS/self-hosted | reportlab (OSS), no paid deps, no network I/O | none |
| A9 | Phase fit (P7) | `pdf/` module + tests only | No `/api/pdp` (P7-03) or frontend (P7-04) coupling; report explicitly defers both | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (pure render, no cross-layer leak)
- [x] Honors locked decisions (no ReAct parser; deterministic headings survive into the builder per the P7-01 blessing)
- [x] Interfaces-before-implementations — consumes the P7-01 `PdpContent` seam only; no re-implementation of the section contract
- [x] Budget posture respected (OSS reportlab)

## Notes
- **Blessed reinterpretation of the ≥4/6 gate.** v1's rule counted heading *substrings* in a raw LLM blob;
  headings are now added deterministically by `PdpContent.to_markdown()` (P7-01), so a substring count is
  meaningless on structured input. The engineer's structural analogue — "≥4 of 6 sections carry a non-trivial
  body" — is the correct, faithful port and is documented on `MIN_REQUIRED_SECTIONS`. This preserves the gate's
  actual intent (reject empty/broken plans) rather than the now-vestigial mechanism. Consistent with the P7-01
  deterministic-heading ruling.
- XML-escape-before-markup in `_inline`/`_resource_line` is a correctness hardening beyond v1 (which fed raw
  text to reportlab); a design plus, not a deviation. Covered by the markup smoke test.
- No follow-ups logged; nothing to unwind later.
