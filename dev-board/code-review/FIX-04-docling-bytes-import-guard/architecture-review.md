# Architecture review — FIX-04-docling-bytes-import-guard · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | Fix stays inside `ingestion/` (parser adapter) + its test | Change confined to `app/ingestion/docling_parser.py` + `tests/test_ingestion_parser.py`; no other module touched | None |
| A2 | Interfaces-before-implementations (§5.1) | Swappable seams for engine construction; unit tests exercise logic without the heavy engine | Adds `DocumentStreamFactory` seam symmetric to the existing `ConverterFactory`; both default to lazy real-impl builders, both injectable with light fakes | None — mirrors the already-blessed converter seam exactly |
| A3 | Budget/CI posture (§11; curated-CI ruling) | Heavy ML deps (docling/torch/sentence-transformers) stay **absent** from the curated CI venv; adapter must import cleanly without them | `_build_default_document_stream` keeps `from docling_core...` deferred to call-time; module import + `DoclingParser()` construction still pull no ML stack; two bytes tests now run (not skip) with docling absent | None — matches `ruling-curated-ci-light-deps` (docling stays out; adapter lazy-imports) |
| A4 | Locked-decision blast radius | Test-hermeticity fix only; no change to datastores/auth/orchestration/embeddings | Untouched; `DoclingParser` public contract byte-for-byte unchanged; real convert path preserved | None |
| A5 | Coverage integrity | Don't blanket-skip and lose coverage where docling is present (task AC3) | Real path still covered via `importorskip("docling")` e2e bytes test; unit tests verify derived stream name + payload against the fake | None |
| A6 | DRY / KISS / YAGNI | Fix proportionate, not over-engineered | Second seam reuses the established DI pattern rather than a bespoke mechanism; the smaller `importorskip` fallback was correctly not needed | None — the "thorough" option was the right call given a pre-existing symmetric seam |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (adapter is a `DocumentParser` impl behind the ABC seam; no cross-layer leak)
- [x] Honors locked decisions (no Postgres/Redis/SSO/embeddings/orchestration surface touched; docling remains the §5.1 primary engine, lazily loaded)
- [x] Interfaces-before-implementations (new `DocumentStreamFactory` seam mirrors `ConverterFactory`; production defaults unchanged)
- [x] Budget posture respected (in-process, no paid dep; curated CI stays free of the ML stack)

## Notes
- Design-consistent with the existing curated-CI test-collection precedent (FIX-01..FIX-03) and my `ruling-curated-ci-light-deps`: heavy ML deps (docling/torch) are deliberately absent from CI, so any code path a unit test transitively reaches must not require them. Wrapping the `DocumentStream` construction in an injectable seam is the structurally correct way to close that gap without weakening the tests — preferable to a blanket skip.
- The engineer verified the P5-02 siblings (`ocr_parser.py`/`composite_parser.py`) have no same-class import into `docling_core`; that check was in-scope and correctly closed — no follow-up.
- Correctness/test-execution verification (both venvs green, ruff/mypy) is the code-reviewer's gate; this review covers design conformance only.
