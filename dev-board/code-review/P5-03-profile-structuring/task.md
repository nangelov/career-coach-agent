# Task P5-03-profile-structuring — Layout-aware structuring + LLM-assisted structured profile
- **Phase:** P5   **Status:** ENG   **Tags:** (B)

## Scope
tasks.md item: "Layout-aware structuring → LLM-assisted parse → structured profile (skills/experience/
education/goals)."

Builds on `backend/app/ingestion/` from `P5-01-ingestion-parser` / `P5-02-ocr-fallback`
(`DocumentParser`, `ParsedDocument`, `CompositeDocumentParser`/`build_default_composite_parser`). Add the
next stage of the §5.1 pipeline: `ParsedDocument` (layout-aware Markdown/JSON, already recovered by
docling/OCR) → LLM-assisted parse → a **structured profile** Pydantic model with the shape the design calls
out: skills, experience, education, goals (this is the schema that will later be persisted into
`profiles.data` JSONB in P5-04 — see `backend/app/repositories/models/identity.py::Profile`, whose `data`
column is intentionally schema-less at the DB layer; **this task owns and defines that shape**).

Concretely:
- A `ProfileSchema` (or similarly named) Pydantic model in `backend/app/ingestion/` (or a `schemas/` module
  if that fits the existing layering better — check `backend/app/schemas/` conventions first) covering at
  least: skills (list), experience (list of roles: title/company/dates/description), education (list:
  institution/degree/field/dates), and goals (career goals extracted or left empty if not present in the CV).
- A structuring step that takes a `ParsedDocument` (its markdown/structured JSON) and produces this
  structured profile via an **LLM-assisted parse** — call the LLM (via the existing `LLMClient`/
  `LLMRouter` surface from `app/llm/`, following the injection pattern used in `agents/planner.py`
  — inject an `LLMCompleter`-shaped dependency, don't construct a client internally) with native tool-calling
  / structured JSON output (no ReAct/text parsing — that pattern is dead per the locked v2 decisions) to map
  the layout-aware text into the schema.
- Handle imperfect/partial documents gracefully: missing sections should yield empty lists/fields, not
  exceptions; validate the LLM's JSON output against the Pydantic schema and raise a typed error
  (e.g. `ProfileStructuringError`) on unrecoverable failures so the P5-04 Celery task can catch one error
  type.
- Unit tests: feed synthetic `ParsedDocument` markdown (a fake CV) through the structuring step with a fake/
  stub `LLMCompleter` (mirroring the fakes used in `agents/planner.py` tests — do not call a real HF
  endpoint in tests) and assert the resulting `ProfileSchema` is correctly populated; also test the
  malformed/partial-output error path.

## Acceptance criteria
- [ ] A structured profile Pydantic schema exists covering skills/experience/education/goals, documented as
      the shape stored in `profiles.data`.
- [ ] A structuring function/class takes a `ParsedDocument` + an injected LLM completer and returns the
      validated structured profile, using native tool-calling/JSON mode — no regex/ReAct text parsing.
- [ ] Missing/partial CV sections degrade gracefully (empty fields, not crashes).
- [ ] Malformed LLM output raises a single typed error the caller can catch.
- [ ] Unit tests cover: full profile, partial/missing-section profile, and the error path — all with a fake
      LLM completer (no network calls).
- [ ] `ruff`, `mypy`, and the full `pytest` suite pass.

## Design references
- dev-board/plan.md: Phase 5 — Document Intelligence & CV/profile (line 98)
- dev-board/app-design-and-features.md: §5.1 (pipeline: "layout-aware structuring → LLM-assisted parse →
  structured profile", lines 196-222), §4 data model (`profiles.data` JSONB, line 146), locked decision
  "Primary LLM native tool-calling ... deletes the v1 ReAct text-parser" (CLAUDE.md).
- `backend/app/repositories/models/identity.py::Profile` — the JSONB target this schema feeds (P5-04 wires
  persistence; this task only defines/produces the shape).
- `backend/app/agents/planner.py` — reference pattern for injecting an `LLMCompleter`/router dependency and
  testing with a fake.

## Constraints / non-goals
- No `POST /api/profile/cv` endpoint, no Celery task, no DB writes, no pgvector embedding — P5-04.
- No `GET/PUT /api/profile` — P5-05.
- No frontend work — P5-07.
- Do not call a real HF/LLM endpoint from tests — inject a fake completer.
- Keep this stage composable so P5-04's Celery task can call:
  `document → CompositeDocumentParser.parse() → structuring step → ProfileSchema` as a straight pipeline.
