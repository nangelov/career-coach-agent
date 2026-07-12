# Task P5-01-ingestion-parser — DocumentParser interface + docling primary engine
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "`ingestion/` — `DocumentParser` interface; **docling** as primary engine."

Create `backend/app/ingestion/` with:
- A `DocumentParser` abstract interface (protocol/ABC) that other engines (docling, OCR fallback, VLM) will
  implement later in P5-02/P5-03. Keep it swappable — agents/services must depend on the interface, not a
  concrete engine.
- A concrete `DoclingParser` implementation (or equivalently named) wrapping the `docling` library: parses
  PDF/DOCX/PPTX/images into structured Markdown/JSON (layout, tables, reading order) per design §5.1.
- Add `docling` as a backend dependency (pyproject.toml via uv).
- Unit tests with a couple of fixture documents (small synthetic PDF/DOCX at minimum; PPTX/image fixtures can
  land in later P5 subtasks if docling's own test fixtures aren't reusable) verifying the interface round-trips
  text/structure.
- Do NOT implement OCR fallback, LLM-assisted structuring, the Celery endpoint, or profile CRUD yet — those are
  separate P5 subtasks (P5-02..P5-06) that will build on this interface.

## Acceptance criteria
- [ ] `backend/app/ingestion/` module exists with a `DocumentParser` interface (ABC/Protocol) documented with
      docstrings describing the contract (input: file path/bytes + mime/type hint; output: structured
      document representation usable by later structuring steps).
- [ ] `DoclingParser` (or similarly named concrete class) implements the interface using `docling`.
- [ ] `docling` is declared in `backend/pyproject.toml` and installs cleanly via `uv sync`.
- [ ] Unit tests exercise the interface end-to-end on at least one real fixture file, asserting extracted text/
      structure is non-empty and reasonable.
- [ ] Existing test suite still passes (`ruff`, `mypy`, `pytest`).

## Design references
- dev-board/plan.md: Phase 5 — Document Intelligence & CV/profile (line 96)
- dev-board/app-design-and-features.md: §5.1 Document Intelligence & OCR (lines 196-222), §8 structure
  (`backend/app/ingestion/` at line 363)

## Constraints / non-goals
- No OCR fallback (Tesseract/OCRmyPDF) — P5-02.
- No LLM-assisted structured-profile parsing — P5-03.
- No `POST /api/profile/cv` endpoint, no Celery task, no pgvector embedding — P5-04.
- No frontend work — P5-07.
- Interfaces-before-implementations: keep `DocumentParser` engine-agnostic so P5-02's OCR fallback and a future
  VLM path can be added without touching callers.
