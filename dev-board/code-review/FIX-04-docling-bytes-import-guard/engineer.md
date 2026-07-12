# Engineer report — FIX-04-docling-bytes-import-guard · Revision 1

## Summary
`DoclingParser._build_convert_source` imported the real `docling_core.types.io.DocumentStream`
whenever it wrapped a `bytes` source — even when the converter was faked in tests. So the two
"does bytes get wrapped with the right name" unit tests transitively required the real `docling`
package, and failed with `ModuleNotFoundError: docling_core` in the CI **curated** venv (which
deliberately excludes docling/torch/sentence-transformers).

Applied the **thorough (injectable-seam) fix** the task preferred, mirroring the existing
`converter_factory` pattern: added a second injectable seam, `document_stream_factory`, so the
bytes-wrapping logic is unit-testable with a lightweight fake and no `docling_core` install. The
default factory still lazily imports the real `DocumentStream`, so production behavior and the
public contract are unchanged. Updated the two affected tests to inject a tiny fake stream — they
now run (not skip) with docling absent, and still run against the real `DocumentStream` in the
existing `importorskip`-guarded end-to-end bytes test where docling is installed.

Checked the P5-02 siblings (`ocr_parser.py` / `composite_parser.py` and their tests): neither
imports `docling_core`, and every bytes path there goes through injected fakes
(`OcrEngine` seam / `_FakeParser`) or `build_default_composite_parser` (construction-only, cheap,
no import). No same-class issue there — nothing to change.

## Files changed
- `backend/app/ingestion/docling_parser.py` — added `DocumentStreamFactory` type + a
  `document_stream_factory` constructor seam (default: `_build_default_document_stream`, which
  lazily imports the real `DocumentStream`); `_build_convert_source` now calls the factory instead
  of importing `docling_core` inline. Added `BinaryIO` import.
- `backend/tests/test_ingestion_parser.py` — added a light `_FakeDocumentStream` (`.name` +
  `.stream`) and wired it into the `_parser()` helper via `document_stream_factory`, so the
  fake-converter tests exercise the bytes-wrapping logic without `docling_core`.

## Key decisions
- **Injectable seam over blanket `importorskip`** (task's preferred option, acceptance criterion 3):
  keeps the two bytes tests meaningful (they still verify the derived stream name + payload) in the
  curated venv, instead of losing that coverage where docling is absent. Mirrors the already-locked
  `converter_factory` seam / DI posture (interfaces-before-implementations; app-design §5.1).
- **Default factory keeps the lazy import** exactly where it was (`_build_default_document_stream`),
  so importing `app.ingestion` and constructing `DoclingParser` still pull no ML stack, and the
  public contract / real convert path is byte-for-byte unchanged (task non-goal: no behavior change).
- **Real coverage preserved**: `test_real_docling_parses_docx_from_bytes` (guarded by
  `importorskip("docling")`) still drives the real `DocumentStream`, so the production wrapping path
  is covered wherever docling is installed.

## How to verify
Reproduce the curated CI venv (per `.github/workflows/backend-ci.yml` install list — no docling):
```bash
uv venv --python 3.11 /tmp/curated && \
uv pip install --python /tmp/curated/bin/python fastapi pydantic pydantic-settings \
  "celery[redis]" openai sqlalchemy asyncpg aiosqlite pgvector alembic joserfc authlib \
  langgraph python-multipart pytest pytest-asyncio ruff mypy
HF_API_TOKEN=ci JWT_SECRET_KEY=ci /tmp/curated/bin/python -m pytest tests/test_ingestion_parser.py -q
```

## Tests (final step — mandatory)
Reproduced the reported failure first in the curated venv (acceptance criterion 1):
```
tests/test_ingestion_parser.py::test_parse_bytes_source_wraps_in_document_stream_with_filename FAILED
tests/test_ingestion_parser.py::test_parse_bytes_derives_extension_from_media_type          FAILED
  ModuleNotFoundError: No module named 'docling_core'   (2 failed, 10 passed, 2 skipped)
```

After the fix — **full suite green in both environments** (a throwaway `pgvector/pgvector:pg16`
Postgres was stood up + migrated, exactly like CI, so the ~40 live-DB integration tests executed
rather than skipping):

- **Dev `.venv` (docling installed):** `420 passed, 1 skipped, 1 warning` (the 1 skip is the
  real-Tesseract OCR test — no Tesseract binary in this env).
- **Curated-equivalent venv (docling absent):** `418 passed, 3 skipped, 1 warning`. The 3 skips are
  the two real-docling e2e tests + the real-Tesseract test (all `importorskip`-guarded). The two
  previously-failing bytes tests now **pass** (not skip).
- Targeted, curated venv: `tests/test_ingestion_parser.py` → `12 passed, 2 skipped` (bytes tests
  pass; only the 2 real-docling e2e tests skip).

Lint/type (dev `.venv`):
```
ruff check         → All checks passed!
ruff format --check → 2 files already formatted
mypy app/ migrations/ → Success: no issues found in 89 source files
```

No test was weakened or deleted; the fix is a production seam + a real fake, keeping the tests'
original intent.

## Self-check
- [x] Meets acceptance criteria (reproduced failure; injectable-seam fix; tests pass with docling
      absent and still run for real with docling present; full suite green in both venvs; ruff+mypy pass)
- [x] No secrets committed; DI/interfaces-before-implementations layering respected (mirrors
      `converter_factory` seam); public `DoclingParser` contract unchanged
- [x] Tests/lints pass (pasted above)
- [x] Did not touch P5-04 files (`app/api/profile.py`, `app/services/profile_ingest.py`,
      `app/schemas/profile.py`, `app/tasks/profile_ingest.py`) — scoped only to
      `docling_parser.py` + `test_ingestion_parser.py`; confirmed `ocr_parser.py`/`composite_parser.py`
      have no same-class issue
