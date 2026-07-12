# Architecture review — P5-03-profile-structuring · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 module placement | New pipeline stage lives in `ingestion/` (or `schemas/`) | `ingestion/profile.py` (schema) + `ingestion/structuring.py` (step), re-exported from `ingestion/__init__.py` | None — correct: it is the next §5.1 ingestion stage, co-located with the P5-01/02 parser seam it consumes. |
| A2 | §5.1 pipeline | `ParsedDocument` → LLM-assisted parse → structured profile (skills/experience/education/goals) | `ProfileStructurer.structure(ParsedDocument) → ProfileSchema` with those four sections | None. |
| A3 | Locked decision: native tool-calling, no ReAct/regex (CLAUDE.md §6, §6.6) | Forced tool-call, structured JSON out, no text parsing | Forced `record_profile` tool (`tool_choice` pinned), args validated via `ProfileSchema.model_validate`; no regex/ReAct anywhere | None — v1 parser stays dead. |
| A4 | Layering (Router→Service→Agent/Repo; no cross-layer leak) | `ingestion` depends on a capability, not the `llm` concrete class | Local `runtime_checkable` `LLMCompleter` Protocol mirroring `LLMRouter.complete` exactly (verified against `llm/router.py:211`); no import of `LLMRouter`; no DB drivers touched | None — mirrors the blessed `agents/planner.py` seam. |
| A5 | Interfaces-before-implementations | Reuse the injected-completer seam, constructor injection | `ProfileStructurer(completer, *, temperature, max_tokens)` — injected, not constructed; production points at any tier as a wiring change | None. |
| A6 | §4 data ownership | `profiles.data` JSONB is schema-less at DB; shape owned by ingestion layer | `ProfileSchema` documented as the `profiles.data` shape; `Profile.data` (identity.py:120) is untyped JSONB; `model_dump()` is JSON-serializable (plain str/list) | None — ownership boundary is clean. |
| A7 | Graceful degradation (§5.1) | Missing sections → empty, not exceptions; single typed error on unrecoverable failure | All fields default empty; partial items kept; empty doc short-circuits (no LLM call); one `ProfileStructuringError` for LLM error / no tool call / non-JSON / non-object / schema-invalid | None — P5-04 Celery task catches one type. |
| A8 | OCR-ran ruling ([[project-ocr-fallback]]) | Structuring must not assume rich `structured`/layout when OCR ran (OCR sets `structured={}`, `markdown==text`) | `content = markdown-or-text`; never reads `.structured`; robust whether docling or OCR produced the doc | None — ruling honored. |
| A9 | Phase fit / no premature coupling | No endpoint, Celery, DB write, or embedding (those are P5-04/05) | Pure structuring step; composable `parser.parse() → structurer.structure()`; no persistence/HTTP/pgvector | None. |
| A10 | Budget posture (§11) | Free/OSS/self-hosted; no paid last-resort | Reuses in-process failover router surface; no new paid dependency | None. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — capability Protocol, no `llm` concrete import, no DB drivers.
- [x] Honors locked decisions (native tool-calling, no ReAct parser; Postgres JSONB target owned here; no MongoDB; in-process posture unchanged).
- [x] Interfaces-before-implementations — `LLMCompleter` seam reused, `ProfileSchema` is the swap-stable contract.
- [x] Budget posture respected (free/OSS/self-hosted).

## Notes
- **DRY win, single design risk to watch (follow-up, non-blocking):** the tool `parameters` are derived from `ProfileSchema.model_json_schema()` — genuinely DRY (contract and validation can't drift). But Pydantic v2 emits nested sub-models (`ExperienceItem`/`EducationItem`) as `$defs` + `$ref`. Some OpenAI-compatible tool-calling backends (and strict-mode function-calling) handle `$ref`/`$defs` inconsistently. This is a provider-compat / runtime concern, not a design deviation, and it is cheap to unwind (flatten with `ref_template`/inlining if GLM-5.2 rejects it). Flagging for the code-reviewer's domain and for the P5-04 integration step to validate against the live model. Not a gate blocker.
- The failure contract deliberately diverges from the planner's fail-soft (planner returns a safe default; structuring raises). This is the correct call here — a silently-empty profile would mask a broken parse as a valid empty CV, and §5.1 wants the ingestion job to surface a real failure. Blessed.
- Empty-document short-circuit returning `ProfileSchema()` without an LLM call is the right graceful path for OCR-recovered-nothing docs and saves a token round-trip.

## Verdict: APPROVED
