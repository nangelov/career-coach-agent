# Architecture review — P5-01-ingestion-parser · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Ingestion code lives in `backend/app/ingestion/` | `types.py` / `parser.py` / `docling_parser.py` / `__init__.py` all under `backend/app/ingestion/` | none |
| A2 | §5.1 single `DocumentParser` seam | "Wrap all of this behind a single `DocumentParser` interface … so engines can be swapped without touching the agents" | `DocumentParser` ABC with one `async parse()` abstractmethod; callers depend only on it; `ParsedDocument`/`DocumentSource` engine-agnostic vocabulary in `types.py` — no docling type leaks into the contract | none |
| A3 | §5.1 primary engine = docling | docling (IBM, MIT): PDF/DOCX/PPTX/images → structured Markdown/JSON w/ layout, tables, reading order | `DoclingParser` wraps docling `DocumentConverter`; maps result → `markdown` / `text` / `structured` (export_to_dict) / `source_format` / `page_count` | none |
| A4 | Interfaces-before-implementations (§5.1 / task) | OCR fallback (P5-02) + VLM path swap in without touching callers | Concrete engine isolated behind ABC; `_MEDIA_TYPE_EXTENSIONS` covers §5.1 CV formats; `ParsedDocument.is_empty` is an explicit hook for P5-02's OCR-fallback decision | none |
| A5 | Phase fit (P5 sequencing) | No OCR fallback, no LLM structuring, no endpoint/Celery/embedding in this task | All four explicitly deferred (P5-02/03/04); no router, service, DB, Celery, or pgvector wiring present | none |
| A6 | Budget posture (§11) | free / OSS / self-hosted | docling is MIT, in-process, no paid API; nothing paid introduced | none |
| A7 | Layering (§8) | Adapter layer sits below services; no DB drivers / router leaks | Pure interface + adapter; no repository, session, or endpoint access | none |
| A8 | CI/ML posture (prior ruling) | Heavy ML deps deferred from curated CI venv; module importable at collection | `import docling` deferred to first `parse()`; converter built lazily behind injectable `converter_factory`; `docling>=2.0.0` in `pyproject.toml` + `uv.lock` (2.107.0) | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — interface+adapter below services, no cross-layer leak
- [x] Honors locked decisions — no ReAct parser; no new datastore; SSO untouched; in-process/self-hosted OSS engine
- [x] Interfaces-before-implementations — `DocumentParser` is a real swap seam (OCR/VLM plug in behind it); mirrors the blessed `EmbeddingClient` / `LLMClient` lazy-import + injectable-factory shape
- [x] Budget posture respected (free/OSS/self-hosted) — MIT docling, in-process

## Notes
- The lazy-`import docling` + `converter_factory` seam is consistent with the blessed `SentenceTransformerEmbeddingClient` pattern (in-process ML behind an injectable encoder, excluded from the curated CI venv). Same posture, correctly applied here — no re-litigation needed.
- `PARTIAL_SUCCESS` accepted / `FAILURE` rejected, with arbitrary engine exceptions normalized to `DocumentParseError`, gives callers one ingestion error type — a good contract boundary for the P5-04 Celery task to catch on.
- Design-risk follow-up (not blocking, for P5-02): §5.1's pipeline splits "has text layer? → direct extract vs rasterize→OCR". This task delegates format/text detection to docling's own convert path rather than an explicit text-layer probe. That is acceptable for the primary engine, but P5-02 must ensure the OCR fallback is triggered off `ParsedDocument.is_empty` (or a low-confidence signal), not re-invented — the hook is already in place.
- `docling` was pre-declared in `pyproject.toml`/`uv.lock` from an earlier scaffold; declaration + lock entry confirmed. Acceptable that a full ~3GB `uv sync` was not re-run given the dep is already locked.
