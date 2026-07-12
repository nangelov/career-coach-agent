---
name: project-profile-structuring
description: Blessed P5-03 profile-structuring — ProfileSchema owns the profiles.data shape; LLMCompleter-injected structuring step, native tool-calling, raise-not-fail-soft
metadata:
  type: project
---

P5-03 (layout-aware structuring → LLM-assisted structured profile) APPROVED rev 1. Blessed pattern for P5-04 (Celery+persist+embed) / P5-05 (GET/PUT profile).

- **Schema ownership boundary:** `ProfileSchema` (+ `ExperienceItem`/`EducationItem`, `ProfileStructuringError`) in `ingestion/profile.py` **is** the canonical shape of `profiles.data` JSONB (`identity.py::Profile.data` stays schema-less at DB). Four §5.1 sections: skills[], experience[], education[], goals[]. All fields default empty; dates kept as free-text str (CV formats too inconsistent for typed dates). `model_dump()` is the JSON P5-04 writes verbatim — do not add a second schema in `schemas/` or the DB layer.
- **Structuring seam mirrors the planner ([[project-agent-graph]]/planner):** `ProfileStructurer(completer)` injects a local `runtime_checkable LLMCompleter` Protocol (mirrors `LLMRouter.complete` exactly), NOT a hard import of `LLMRouter` — `ingestion` depends on a capability, layering preserved. Forced `record_profile` tool-choice, native tool-calling, no ReAct/regex.
- **Tool schema derived from Pydantic** (`ProfileSchema.model_json_schema()`) = DRY single source of truth. Risk logged (non-blocking): nested sub-models emit `$defs`/`$ref`; verify GLM-5.2 accepts it at P5-04 live-integration, else flatten. Not a design deviation.
- **Failure contract diverges from planner fail-soft on purpose:** partial CV → empty fields (graceful, no raise); unrecoverable (LLM error / no tool call / non-JSON / non-object / schema-invalid) → single `ProfileStructuringError` so P5-04 Celery catches one type. Silently-empty-on-malformed is explicitly rejected (would mask a broken parse). Empty doc short-circuits to `ProfileSchema()` with no LLM call.
- **OCR-ran ([[project-ocr-fallback]]) honored:** uses `markdown or text`, never reads `.structured` — robust whether docling or OCR produced the doc.

**Why:** §5.1 pipeline stage; §4 puts the CV shape in JSONB owned by the ingestion layer, not the schema.
**How to apply:** P5-04 must call `parser.parse() → structurer.structure()` as a straight pipeline in the Celery task (§5.1 "OCR/doc-intel as background job") and persist `model_dump()` into `profiles.data`; do not re-derive the shape. P5-05 read/write endpoints validate against this same `ProfileSchema`.
