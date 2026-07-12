---
name: check-ingestion-parser-tasks
description: Reviewing P5 backend/app/ingestion/ document-parser tasks — lazy docling SDK isolation, injectable converter seam, Any-typed engine boundary for curated-venv mypy, real-fixture test
metadata:
  type: project
---

Review checklist for `backend/app/ingestion/` (P5 doc-intelligence). P5-01 shipped the
`DocumentParser` ABC (`parser.py`) + `DoclingParser` adapter (`docling_parser.py`) +
engine-agnostic `types.py` (`ParsedDocument`, `DocumentSource = str | bytes`).

**Why:** docling is the primary engine but is deliberately EXCLUDED from the CI curated
venv (heavy torch/OCR ML stack) — see [[project-curated-ci-venv-mypy]]. So the same lazy-import
+ injectable-seam posture as `SentenceTransformerEmbeddingClient` is mandatory.

**How to apply:**
- **SDK isolation + lazy import:** `import docling` / `docling_core` may only appear INSIDE
  method bodies of `docling_parser.py` (deferred, `# noqa: PLC0415`), never at module top
  or in `__init__.py`/`parser.py`/`types.py`. Constructing `DoclingParser()` must NOT import
  docling or build the converter (there's a test asserting `parser._converter is None`).
- **Injectable converter seam:** `converter_factory` arg lets tests inject a fake converter
  mimicking docling's `ConversionResult` shape — so unit tests run in the curated venv with no
  docling install. Fakes live in the test module (external SDK shape), not `tests/fakes.py`.
- **Curated-venv mypy safety:** every function that touches a docling value must be annotated
  `-> Any` (or return a locally-constructed concrete type), because with docling absent it all
  resolves to `Any` and `strict`'s `warn_return_any` fires if an Any is returned into a
  concrete annotation. Dev-venv mypy passes with REAL docling types (stricter) → curated (Any)
  is looser EXCEPT for that return-Any trap. P5-01 got this right (all engine-boundary fns
  `-> Any`).
- **Real fixture test:** at least one end-to-end test on a committed fixture, guarded by
  `pytest.importorskip("docling")` at the test-body start (NOT collection) so it skips cleanly
  in CI. Prefer DOCX — docling's DOCX path uses the simple pipeline (no model download,
  offline-safe); PDF/image trigger a layout-model download and belong in later P5 subtasks.
- **Known nits seen (not gates):** the `except UnsupportedDocumentError: raise` inside `parse`'s
  try can be dead code if the raise actually happens in `_build_convert_source` (called before
  the try); `_to_parsed_document` running outside the try means docling `export_*` errors aren't
  normalized to `DocumentParseError`. Both are minor/defensive.
