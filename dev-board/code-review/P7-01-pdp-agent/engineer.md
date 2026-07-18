# Engineer report — P7-01-pdp-agent · Revision 1

## Summary
Implemented the PDP agent: a typed, off-request generator that takes the already-parsed
structured profile (P5 `ProfileSchema`), the P6 skills gap (`SkillsGapResult`), the career
goal + target date, and produces the six-section v1 PDP contract as a structured
`PdpContent`. Recommendations are grounded in real courses pulled from the shared
learning-resource corpus (P6-06 skill-keyed lookup) and carried structurally; the profile
and market/learning text are fenced as untrusted DATA (S2 §7.3); the plan is produced via a
forced `record_pdp` native tool call (no ReAct parser). All degraded paths (missing profile
/ unmined role / no resources / LLM failure) degrade without raising.

## Files changed
- `backend/app/schemas/pdp.py` (new) — `PdpContent` (six section fields + `status` +
  cited `resources`), `LearningResourceRef`, `SECTION_HEADINGS` (single source of truth for
  the v1 heading contract), and `to_markdown()` that adds canonical `## <Heading>` markers.
- `backend/app/agents/pdp_agent.py` (new) — `generate_pdp(...)` entry point, `PDP_TOOL_SCHEMA`
  (forced tool), `ResourceLookup` DI seam, prompt assembly with fenced untrusted profile +
  market/learning blocks, skill-keyed resource lookup with URL dedup, fail-soft parsing.
- `backend/app/agents/__init__.py` — export `generate_pdp`, `PDP_TOOL_NAME`,
  `PDP_TOOL_SCHEMA`, `ResourceLookup`.
- `backend/tests/test_pdp_agent.py` (new) — 9 unit tests (happy path, fencing/forced-tool,
  degraded profile/role/resources, DB-error soft-fail, URL dedup, LLM-failure fallback,
  partial-args coercion).

## Key decisions
- **Structured output via forced tool-call, headings added deterministically.** The model
  writes only section *bodies* through `record_pdp`; `PdpContent.to_markdown()` adds the six
  canonical `##` headings. This makes ReAct/tool-call scaffolding structurally impossible in
  the output and guarantees the rendered markdown passes the P7-02 `validate_pdp_response`
  gate (real headings, ≥500 chars) — mirrors planner `record_plan` / market
  `record_requirements` (locked decision §6, task acceptance #2).
- **Skill-keyed lookup, not a second similarity search.** Recommendations use the
  purpose-built P6-06 `list_resources_for_skill` (task allows "similarity search / skill-keyed
  lookup"). KISS/YAGNI: no embedder needed, keeps the agent free of the ML stack. Cited
  resources are carried structurally in `PdpContent.resources` (deduped by URL, each remembers
  which gap skill(s) it covers) so P7-02 renders the real citation list rather than trusting
  free text — the "grounded, not hallucinated" requirement (§5.7).
- **Untrusted fencing reuses `fence_untrusted`.** CV-derived profile and crawled
  learning-resource/gap text are fenced as DATA (same pattern as responder/market_agent, no
  new one — S2 §7.3). Career goal/target date are the authenticated user's own request →
  trusted plain user turn.
- **Graceful degradation via `PdpContent.status`.** `profile_missing` (no LLM call, clear
  "upload a CV" plan), `role_profile_missing` (best-effort plan from profile+goal, empty
  gap/resources), and LLM-failure fallback all return a valid renderable document; never
  raises — P7-03 branches on `status` (§5.1, task constraint).
- **DI seam `ResourceLookup`** (structural `session()` provider) — production shared pool
  injected by P7-03; tests inject a scripted session. No SQLAlchemy in the agent body beyond
  the repository helper (Router→Service/Repo layering, §8).

## How to verify
```
cd backend && source .venv/bin/activate
python -m pytest tests/test_pdp_agent.py -q
ruff check app/agents/pdp_agent.py app/schemas/pdp.py tests/test_pdp_agent.py
mypy app/agents/pdp_agent.py app/schemas/pdp.py
```

## Tests (final step — mandatory)
- `python -m pytest tests/test_pdp_agent.py -q` → **9 passed**.
- Focused regression (agents/schemas/market/learning/skills-gap/graph):
  `... test_agent_graph test_agent_planner test_agent_responder test_skills_gap
  test_learning_resources test_market_agent test_p6_exit_verification` → **114 passed, 2
  skipped**.
- **Full suite:** `python -m pytest -q` → **618 passed, 59 skipped** (skips are the live-DB
  `*_postgres` integration tests — no Postgres in this run; unrelated to this task).
- `ruff check` → All checks passed. `mypy` (strict) → Success, no issues.
- No failures; no code or test changes needed to reach green.

## Self-check
- [x] Meets acceptance criteria: typed `generate_pdp` producing all six grounded sections;
      no ReAct scaffolding can leak (forced tool-call + deterministic headings); unit tests
      cover happy + all three degraded paths; untrusted profile/resource text is fenced.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (agent uses the
      `learning_resources` repository helper via an injected session provider, no driver).
- [x] Tests/lints pass (results pasted above).

## Notes / flags
- `pdps` table schema untouched (P2-05) — `PdpContent.model_dump()` fits the `content` JSONB
  column (`dict[str, Any]`); `career_goal`/`target_date` are separate columns the P7-03
  endpoint owns, so they are `generate_pdp` inputs, not part of `PdpContent`.
- Out of scope (left for their tasks): PDF builder (P7-02), `/api/pdp` endpoint + composition
  wiring (P7-03), frontend (P7-04).
