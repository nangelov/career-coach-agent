# Code review — FIX-04-docling-bytes-import-guard · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | backend/app/ingestion/docling_parser.py:52 | `DocumentStreamFactory` param is typed `BinaryIO` but the sole caller passes a concrete `BytesIO` (`_build_convert_source:145`); the real `DocumentStream` also accepts a broader stream. Fine as-is — noted only for symmetry with `ConverterFactory`. | None required. |

## Notes
Independently reproduced and verified every acceptance criterion:

- **Root cause / fix correctness.** The inline `from docling_core.types.io import DocumentStream` in `_build_convert_source` was the real import site. It is replaced by a `document_stream_factory` injectable seam mirroring the existing `converter_factory` pattern; the default `_build_default_document_stream` keeps the `docling_core` import deferred inside the method body (`# noqa: PLC0415`). Constructing `DoclingParser()` still imports no ML stack. Public contract unchanged.
- **Docling-absent run (curated-venv simulation via a meta-path import blocker for `docling`/`docling_core`):** `tests/test_ingestion_parser.py` → 12 passed, 2 skipped. The two previously-failing bytes tests (`test_parse_bytes_source_wraps_in_document_stream_with_filename`, `test_parse_bytes_derives_extension_from_media_type`) now **PASS** (not skip), verifying the derived stream name + payload against the injected `_FakeDocumentStream`. The only skips are the two `importorskip("docling")`-guarded real e2e tests.
- **Docling-present run (dev `.venv`):** 14 passed — real-coverage bytes path (`test_real_docling_parses_docx_from_bytes`) still exercises the real `DocumentStream`.
- **`test_parse_bytes_without_hint_raises_unsupported` unaffected** — `_stream_name` raises `UnsupportedDocumentError` before the factory is reached; passes in both environments.
- **Sibling check honored:** grep confirms `ocr_parser.py` / `composite_parser.py` import no `docling`/`docling_core`; no same-class issue there.
- **Lint/type:** `ruff check` on both changed files → clean; `mypy app/ingestion/docling_parser.py` → clean. Engineer's `-> Any` engine-boundary annotations preserved, so curated-venv mypy stays green.
- No test was weakened or deleted; the fix adds a production seam + a faithful fake, keeping the original test intent. Correctness, security, and quality all clear — the change is small, hermetic, and matches the locked lazy-import/injectable-seam posture for docling.
