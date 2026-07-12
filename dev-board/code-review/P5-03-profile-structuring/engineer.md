# Engineer report — P5-03-profile-structuring · Revision 1

## Summary
Added the next stage of the §5.1 ingestion pipeline: an LLM-assisted structuring step that
maps a `ParsedDocument` (layout-aware Markdown from P5-01/P5-02) into a structured
`ProfileSchema` (skills / experience / education / goals) using **native tool-calling**
(no ReAct/regex — locked v2 decision). This owns and defines the shape later persisted into
`profiles.data` JSONB (P5-04). Injection + fake-completer testing mirror `agents/planner.py`;
no test touches a real HF endpoint.

## Files changed
- `backend/app/ingestion/profile.py` — new. `ProfileSchema` + `ExperienceItem` / `EducationItem`
  sub-models (all fields default to empty for graceful degradation) and the single typed
  `ProfileStructuringError`. Documented as the shape stored in `profiles.data`.
- `backend/app/ingestion/structuring.py` — new. `ProfileStructurer` (injected `LLMCompleter`
  structural Protocol), `PROFILE_TOOL_SCHEMA`/`PROFILE_TOOL_NAME`, forced-tool-choice call, and
  `_parse_profile` validating the tool-call arguments into `ProfileSchema`.
- `backend/app/ingestion/__init__.py` — re-export the new public symbols (+ `__all__`).
- `backend/tests/test_ingestion_structuring.py` — new. 15 unit tests: full CV, partial/missing
  sections, empty-doc short-circuit, all malformed/error paths, and the tool-call contract.

## Key decisions
- **Native tool-calling, forced `record_profile` (design §5.1, CLAUDE.md locked decision).**
  Same schema-in / structured-out contract as `planner.py`; the v1 ReAct text-parser stays dead.
- **Tool schema derived from the Pydantic model** (`ProfileSchema.model_json_schema()`) rather
  than hand-written — the LLM contract and the validation model are a single source of truth and
  cannot drift (DRY). (The smaller planner schema is hand-written; the nested profile schema
  benefits more from generation.)
- **Injected `LLMCompleter` as a local structural `Protocol`** (not a hard import of `LLMRouter`),
  exactly as the planner does — `ingestion` depends on a capability, not the `llm` concrete class,
  and layering is preserved. Constructor injection keeps the model-tier choice a wiring change.
- **Failure contract deliberately differs from the planner's fail-soft.** A *partial* CV degrades
  gracefully (missing sections → empty lists/fields via schema defaults, partial items kept). An
  *unrecoverable* problem (LLM error, no tool call, non-JSON / non-object args, schema-invalid
  payload) raises the single `ProfileStructuringError` so P5-04's Celery task catches one type.
  An empty document short-circuits to an empty profile without an LLM call.
- **Free-text date strings** on experience/education entries (not typed dates): CV date formats
  are inconsistent; a strict date type would turn a usable CV into a validation failure.
- **Composable for P5-04**: `parser.parse() → structurer.structure()` is a straight pipeline.

## How to verify
```
cd backend
.venv/bin/ruff check app/ingestion/ tests/test_ingestion_structuring.py
.venv/bin/ruff format --check app/ingestion/profile.py app/ingestion/structuring.py
.venv/bin/mypy app/ingestion/
.venv/bin/pytest tests/test_ingestion_structuring.py -q
```

## Tests (final step — mandatory)
- `ruff check` (new files + whole `app/ingestion/`) — **All checks passed!**
- `ruff format --check` — **3 files already formatted**
- `mypy app/ingestion/` (strict) — **Success: no issues found in 11 source files**
- `pytest tests/test_ingestion_structuring.py` — **15 passed**
- Full suite `pytest -q` — **362 passed, 44 skipped** (skips are the pre-existing docling/live-DB
  guards; no new skips, no failures). No test needed fixing.

## Self-check
- [x] Meets acceptance criteria (schema for skills/experience/education/goals documented as the
      `profiles.data` shape; injected-completer structuring via native tool-calling; graceful
      partial-CV degradation; single typed error on malformed output; full/partial/error unit
      tests with a fake completer; ruff+mypy+pytest green).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (ingestion depends on a
      structural `LLMCompleter` capability, not the `llm` concrete class; no DB drivers touched).
- [x] Tests/lints pass (pasted above).

## Response to review (revisions only)
- N/A — first revision.
