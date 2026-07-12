# Task FIX-04-docling-bytes-import-guard — Guard bytes-source ingestion unit tests from real docling import
- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (B) (T)

## Scope
While implementing `P5-04-cv-upload-endpoint`, the engineer ran the CI-equivalent **curated** venv (the one
`.github/workflows/backend-ci.yml` actually installs — no `docling`/`sentence-transformers`/`torch`, per
design) and found two pre-existing failures from `P5-01-ingestion-parser`:

```
tests/test_ingestion_parser.py::test_parse_bytes_source_wraps_in_document_stream_with_filename
tests/test_ingestion_parser.py::test_parse_bytes_derives_extension_from_media_type
FAILED with ModuleNotFoundError: docling_core
```

Root cause: `backend/app/ingestion/docling_parser.py::DoclingParser._build_convert_source` always does
`from docling_core.types.io import DocumentStream` when wrapping a `bytes` source — **regardless of whether
the `converter_factory` is faked**. So any unit test that calls `parser.parse(bytes_source, ...)` transitively
requires the real `docling` package to be installed, even though the test injects a fake converter and never
calls the real engine. These tests pass in the full dev `.venv` (docling installed) but will fail in real CI
(curated venv, docling intentionally excluded — see `backend-ci.yml` comments around the curated install).

Fix this without weakening the intent of the tests:
- Prefer **not** requiring real docling for pure "does bytes get wrapped with the right name" tests: consider
  making the `DocumentStream` construction itself go through an injectable seam (mirroring the
  `converter_factory` pattern) so unit tests can verify the wrapping logic with a lightweight fake — this
  keeps the tests meaningful without docling installed and is the more thorough fix.
- If that refactor is out of proportion to the bug, the minimal acceptable fix is to add
  `pytest.importorskip("docling_core", reason="...")` to the two affected tests (matching the existing
  guard pattern already used for the real end-to-end docling tests in the same file), so they skip cleanly in
  the curated CI venv instead of failing, while still running for real wherever `docling` is installed.
- Verify `test_parse_bytes_without_hint_raises_unsupported` is unaffected (it raises before reaching the
  docling import) — leave it as-is if so.
- Check `backend/app/ingestion/ocr_parser.py` / `composite_parser.py` (P5-02) for the same class of issue —
  any test there that passes `bytes` through a path that imports `docling_core` (directly or via
  `DoclingParser`) needs the same treatment.

## Acceptance criteria
- [ ] Reproduce the failure in a curated-equivalent venv (no docling installed) before fixing, to confirm root
      cause matches the report above.
- [ ] Fix applied (either the injectable-seam refactor or the `importorskip` guard) so the affected tests pass
      or skip cleanly with **no** `docling`/`docling_core` installed.
- [ ] The same tests still exercise real behavior (pass, not skip) in an environment where `docling` **is**
      installed — do not just blanket-skip and lose coverage where the dependency is present.
- [ ] Full `pytest` suite green in both the dev `.venv` (docling installed) and a curated-equivalent
      environment (docling absent) — paste both results.
- [ ] `ruff` + `mypy` still pass.

## Design references
- `.github/workflows/backend-ci.yml` — curated install rationale (excludes torch/docling/sentence-transformers
  deliberately; this is what CI actually runs).
- `backend/app/ingestion/docling_parser.py::_build_convert_source` — the real import site.
- `backend/tests/test_ingestion_parser.py` — existing `importorskip("docling", ...)` pattern already used for
  the two real end-to-end tests in the same file (mirror it).
- Precedent: `dev-board/code-review/FIX-01-backend-test-deps/`, `FIX-02-mypy-ci-curated-deps/`,
  `FIX-03-pytest-ci-missing-deps/` — this repo's established pattern for curated-CI-venv test-collection fixes.

## Constraints / non-goals
- Do not touch `P5-04-cv-upload-endpoint`'s own files — this is scoped to the P5-01/P5-02 ingestion test gap
  it surfaced. `P5-04` is reviewed separately.
- Do not change the `DoclingParser` public contract/behavior — this is a test-hermeticity fix, not a feature
  change.
