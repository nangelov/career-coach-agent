# Engineer report — P5-01-ingestion-parser · Revision 1

## Summary
Added the engine-agnostic document-ingestion seam for P5 per design §5.1: a `DocumentParser`
ABC that callers (services, the later P5-03 profile parser, the P5-04 Celery task) depend on,
plus the primary `DoclingParser` implementation wrapping IBM `docling` (PDF/DOCX/PPTX/images →
structured Markdown/JSON with layout/tables/reading-order). The engine SDK is imported lazily
so `app.ingestion` imports cleanly even where the ML stack isn't installed (CI), and the convert
backend is behind an injectable factory seam so tests never install docling or download a model.
OCR fallback (P5-02), LLM-assisted structuring (P5-03), and the upload endpoint/Celery task
(P5-04) are explicitly out of scope and plug in behind the same contract later.

## Files changed
- `backend/app/ingestion/types.py` — new. `ParsedDocument` (markdown / text / structured JSON /
  source_format / page_count / metadata + `is_empty`) and the `DocumentSource = str | bytes`
  alias — the engine-agnostic vocabulary.
- `backend/app/ingestion/parser.py` — new. `DocumentParser` ABC (contract documented: path/bytes
  + filename/media_type hint → `ParsedDocument`) and the `DocumentParseError` /
  `UnsupportedDocumentError` exceptions.
- `backend/app/ingestion/docling_parser.py` — new. `DoclingParser`: lazy `import docling` +
  lazy `DocumentConverter` build (never at import/construction), injectable `converter_factory`
  seam, `bytes`→`DocumentStream` wrapping with format-hint derivation, status/error normalization,
  and `ConversionResult`→`ParsedDocument` mapping. Blocking `convert` runs via `asyncio.to_thread`.
- `backend/app/ingestion/__init__.py` — was a one-line stub; now re-exports the public surface.
- `backend/tests/test_ingestion_parser.py` — new. 12 interface/adapter tests (fake converter, run
  everywhere) + 2 real end-to-end tests on a DOCX fixture (guarded by `importorskip("docling")`).
- `backend/tests/fixtures/ingestion/sample_cv.docx` — new. Small synthetic CV fixture (binary).
- `backend/pyproject.toml` — no change: `docling>=2.0.0` was already declared and is in `uv.lock`.

## Key decisions
- **ABC + lazy SDK import + injectable seam** mirrors the existing `EmbeddingClient` /
  `SentenceTransformerEmbeddingClient` pattern (design §6, ports-and-adapters). Rationale: docling
  pulls torch + layout/OCR models and is deliberately excluded from the CI curated venv
  (`.github/workflows/backend-ci.yml`); deferring `import docling` to the first `parse()` call
  keeps `app.ingestion` importable at collection in CI, and the `converter_factory` lets tests
  inject a fake so no model is downloaded.
- **Interface-before-implementation** (design §5.1 / task constraint): callers depend on
  `DocumentParser`, so P5-02's OCR fallback and a future VLM path swap in without touching callers.
- **`bytes` sources require a format hint.** docling detects format from a name/extension; for
  in-memory uploads I wrap bytes in a docling `DocumentStream` whose name is derived from
  `filename` (preferred) or a `media_type`→extension map, else raise `UnsupportedDocumentError`.
- **`PARTIAL_SUCCESS` is accepted, `FAILURE` rejected**; arbitrary engine exceptions are normalized
  to `DocumentParseError` so callers catch one ingestion error type.
- **Real end-to-end test uses DOCX, not PDF.** docling's DOCX path uses the simple pipeline (no ML
  model download — verified offline), so the test exercises the *actual* engine end-to-end while
  staying CI/sandbox-safe; PDF/image would trigger a layout-model download and are left to later
  P5 subtasks per the task's fixture note.

## How to verify
```
cd backend
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app/ migrations/
.venv/bin/python -m pytest tests/test_ingestion_parser.py -q   # 14 pass (incl. 2 real docling)
```

## Tests (final step — mandatory)
- `ruff check .` → All checks passed; `ruff format --check .` → 130 files already formatted.
- `mypy app/ migrations/` → Success: no issues found in 78 source files.
- `pytest tests/test_ingestion_parser.py -q` → **14 passed** (12 fake-converter + 2 real docling
  on the DOCX fixture).
- Full suite `pytest -q` → **326 passed, 43 skipped** (skips are the pre-existing live-DB
  integration tests when no Postgres is bound; unrelated to this task). No failures.

## Self-check
- [x] Meets acceptance criteria: `app/ingestion/` module with documented `DocumentParser` ABC;
  `DoclingParser` implements it via docling; `docling` declared in pyproject + in `uv.lock` and
  importable; unit tests exercise the interface end-to-end on a real DOCX fixture asserting
  non-empty/reasonable text+structure; existing suite still green (ruff/mypy/pytest).
- [x] No secrets committed; layering respected — this is the interface + adapter layer below
  services (no DB/driver access, no router/endpoint wiring, matching interfaces-before-impls).
- [x] Tests/lints pass (output pasted above).

## Notes
- `docling` was already present in `pyproject.toml`/`uv.lock` from an earlier scaffold; I did not
  re-run a full `uv sync` (it pulls ~3GB ML/CUDA and the dep is already satisfied) — confirmed the
  declaration, lock entry, and import instead.
- The docling-result fakes live in the test module (not `tests/fakes.py`) intentionally: they
  mimic an *external* SDK result shape, not a first-party port.
