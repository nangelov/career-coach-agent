# Task P5-08-verify — P5 exit: scanned PDF + PPTX CV parse async into a structured, RAG-grounded profile
- **Phase:** P5   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: "Scanned/image PDF and PPTX CV both parse async into a structured profile and are
RAG-grounded."

This is the phase-level integration verification pulling together P5-01..P5-07 (`DocumentParser`/docling,
OCR fallback, LLM-assisted structured-profile parse, the `POST /api/profile/cv` Celery task +
`GET /api/jobs/status/{task_id}` polling, `GET/PUT /api/profile`, and the frontend upload/profile UI).
Mirror how `P2-08-verify`/`P2-09-integration-verify`, `P3-07-verify`, and `P4-10-verify` composed their
phase-exit verification (see `dev-board/code-review/P4-10-verify/engineer.md` for the most recent example of
the expected shape/rigor) — do not just re-run each prior task's own suite in isolation; prove the **whole
chain** end-to-end and report a clear yes/no on the exit criterion.

Specifically verify, ideally with one or two composed integration tests (real pipeline wiring, fake only the
true external edges — LLM completions, embeddings if a live model isn't available — mirroring the P4-10
precedent of "real router stack, in-memory/fake ports, no external creds/live HF"):

1. **A scanned/image PDF** (no usable text layer) uploaded via `POST /api/profile/cv` triggers the P5-02 OCR
   fallback (not just the docling primary path) and still yields a non-trivial structured profile.
2. **A PPTX CV** uploaded the same way parses via the primary (docling) engine into a structured profile.
3. **Both run asynchronously** — the endpoint returns `202` + `task_id` immediately (no in-request blocking
   parse), and `GET /api/jobs/status/{task_id}` shows real progress (pending → in-progress-with-stage →
   success) for both documents.
4. **The result is a "usable" structured profile** — non-empty skills/experience/education for a
   realistic fixture CV (an all-empty profile from a real CV is a fail, not just "parses without throwing").
5. **The profile is persisted and reusable** — `GET /api/profile` returns the parsed profile afterward with
   no re-upload (P5-05), and a second `POST /api/profile/cv` for the same user replaces it (P5-04's
   "exactly one `user_cv` doc" invariant) rather than accumulating duplicates.
6. **RAG-grounded**: the parsed CV's chunks are retrievable by the P4 RAG agent
   (`app/agents/rag_agent.py` / `app/repositories/vector_search.py::hybrid_search_chunks`) — i.e. a
   representative query relevant to the fixture CV's content returns that CV's `KbChunk`s (with
   `KbDocument.source_type == "user_cv"`) among the grounded snippets/citations, proving the P5 ingestion
   pipeline and the P4 retrieval pipeline are actually wired together end-to-end, not just independently
   tested.
7. **Frontend**: the P5-07 upload/progress/profile-view-edit UI works against this contract (confirm via its
   existing/extended test suite — a full live browser click-through is not required if automated coverage
   already proves the contract, matching the P4-10 precedent).

## Acceptance criteria
- [ ] All 7 points above are covered by automated tests (composed/integration-level where prior per-task
      tests only proved pieces in isolation) or a clearly documented manual/live-infra verification for any
      part that genuinely requires a live HF endpoint/real docling model download/real Tesseract binary —
      mirror how P2-09/P4-10 documented what could and couldn't run live in this environment.
- [ ] Full backend test suite green (`ruff`, `mypy` on `app/`+`migrations/` per CI scope, `pytest`).
- [ ] Full frontend test suite green (`lint`, `build`/`type-check`, `jest`).
- [ ] Explicitly check whether the mypy noise flagged as "pre-existing, not mine" in
      `dev-board/code-review/P5-06-task-status/engineer.md` (`tests/test_ingestion_ocr.py`,
      `tests/test_ingestion_parser.py`, `tests/test_llm_router.py`, `tests/test_p4_exit_verification.py`)
      is still present; since CI's mypy gate is scoped to `app/`+`migrations/` (not `tests/`) this is
      non-gating, but report its current state (fixed incidentally, still present, or worsened) so it isn't
      silently lost track of.
- [ ] Report clearly states: does the current implementation meet the full P5 exit criterion as written? If a
      gap is found in any prior P5 task's work, flag it precisely (which task, what's missing) rather than
      silently patching around it, so the orchestrator can route a fix to the right task.

## Design references
- `dev-board/plan.md` — P5 exit criterion: "a scanned/image PDF and a PPTX CV both parse (async, with
  progress) into a usable structured profile and become RAG-grounded."
- `dev-board/app-design-and-features.md` §5.1 (ingestion pipeline), §5.3 (Celery/progress), §4 (`profiles`,
  `kb_documents`/`kb_chunks`).
- `dev-board/code-review/P5-01-ingestion-parser/` through `P5-07-frontend-cv-upload/` — everything under
  verification here.
- `dev-board/code-review/P4-10-verify/engineer.md` — the precedent for how a phase-exit verification task
  should compose real pipeline wiring with faked external edges and report point-by-point.

## Constraints / non-goals
- This task should not introduce new endpoints/features — it's verification of P5-01..P5-07's work. If a gap
  requires real implementation changes, flag it rather than silently patching around it (the orchestrator
  will route a follow-up fix task).
- Do not weaken or delete existing tests to make the suite "pass" — if something is genuinely broken, report
  it as a gap.
- Fixture documents: use small synthetic files (a genuinely scanned/rasterized image-only PDF and a PPTX)
  rather than requiring copyrighted real CVs — reuse/extend the fixtures already added in P5-01/P5-02
  (`backend/tests/fixtures/ingestion/`) where possible.
