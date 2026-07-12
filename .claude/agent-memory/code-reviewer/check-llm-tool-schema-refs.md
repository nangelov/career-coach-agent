---
name: check-llm-tool-schema-refs
description: Reviewing tool schemas derived from nested Pydantic models via model_json_schema() — the $defs/$ref runtime-compat risk for HF native tool-calling
metadata:
  type: project
---

When a task derives an LLM tool schema from a Pydantic model with
`Model.model_json_schema()` (DRY: schema + validation = one source of truth), check
whether the model is **nested** (has sub-models in lists/fields). Pydantic emits nested
sub-models as `$defs` + `{"$ref": "#/$defs/..."}` — not inline.

**Why it matters:** the flat hand-written schemas (e.g. `agents/planner.py::PLANNER_TOOL_SCHEMA`)
avoid refs. P5-03 `ingestion/structuring.py::PROFILE_TOOL_SCHEMA` is the first schema handing a
provider `$ref`/`$defs` (nested `ExperienceItem`/`EducationItem`). OpenAI structured-outputs
dereferences refs, but **HF Inference Providers behavior for GLM/Qwen native tool-calling is
unverified** — a backend that doesn't resolve refs returns malformed nested items.

**How to apply:**
- Deriving from a nested model is fine and good DRY — do NOT gate on it. It is a **minor/note**,
  because tasks that only define the schema can't call a real endpoint (test constraint).
- Flag it so the **wiring task** (P5-04 endpoint/Celery) verifies the derived schema round-trips
  through the real primary+secondary models on a real CV. If refs aren't honored, the fix is to
  flatten `$defs` inline while keeping model-derived generation.
- Verify locally with `Model.model_json_schema()` (env-guarded: importing `app.ingestion.*` pulls
  `app.config.Settings`, so set `HF_API_TOKEN=x DATABASE_URL=x JWT_SECRET_KEY=x`). If `$defs` in
  output → refs are in play.
- The malformed-runtime case degrades safely IF the structurer validates the payload and raises a
  single typed error (P5-03 does: `ProfileStructuringError`) — confirm that safety net exists.
