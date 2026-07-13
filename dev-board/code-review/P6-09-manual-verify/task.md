# Task P6-09-manual-verify — P6 exit: cited ranked requirements + gap + cache + redirect
- **Phase:** P6   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: *""PM → AI Solution Architect" returns cited, ranked requirements + a gap; second user hits
the cache (no re-extraction); "find me jobs in Berlin" is redirected, not answered with listings."*

This is the phase-level integration verification pulling together P6-01..P6-08 (taxonomy seed, role_profiles/
job_postings schema, Tavily search pool, market_agent + mining + topic guardrail, skills gap, learning-resource
corpus, roles API, frontend UI). Mirror how `P4-10-verify`/`P5-08-verify` composed their phase-exit
verification (read `dev-board/code-review/P5-08-verify/task.md` + `engineer.md` for the expected shape/rigor)
— do not just re-run each prior task's own suite in isolation; prove the **whole chain** end-to-end and report
a clear yes/no on the exit criterion.

Specifically verify, ideally with one or two composed integration tests (real pipeline wiring, fake only the
true external edges — LLM completions, Tavily HTTP, embeddings if a live model isn't available — mirroring the
P4-10/P5-08 precedent of "real stack, in-memory/fake ports, no external creds/live HF/live Tavily"):

1. **End-to-end mining → requirements**: a target role with no prior `role_profiles` row (e.g. "AI Solution
   Architect") run through `mine_role_requirements` (fake taxonomy hit + fake search/crawl + scripted LLM
   extractor) produces a `role_profiles` row with **frequency-ranked, cited** requirements, and
   `GET /api/roles/{role}/requirements` (after the mine completes) returns that data at `200` with visible
   evidence/citations — not a bare skill list.
2. **Skills gap**: a fixture user profile (skills list) diffed against that role's requirements via
   `GET /api/roles/{role}/gap` returns a sensible matched/gap split, ordered by frequency/weight.
3. **Cache reuse — "second user hits the cache, no re-extraction"**: a second `GET /api/roles/{role}/requirements`
   call for the **same** (or equivalently-normalized) role does **not** re-run the mining pipeline / re-hit
   Postgres for canonicalization (assert via a spy/counter on the mining-enqueue port and/or the DB
   query, per P6-07's own test seams) — served from the Redis cache P6-07 built.
4. **Topic guardrail — redirect, not listings**: a planner-classified `JOB_HUNTING` turn (e.g. *"find me AI
   architect jobs in Berlin"*) runs through the compiled graph and produces a response that is a
   **market-requirements redirect** — critically, confirm there is **no** code path anywhere in the graph/
   tools that could produce a listings-style answer (no `job_postings` rows are ever serialized back to a
   chat response; the `MARKET_INTEL` worker only ever returns `role_profiles`-derived requirement content).
   Also confirm an `OFF_TOPIC` turn (e.g. *"is this rash serious?"*) short-circuits to the canned refusal with
   no LLM/worker call, per P6-04's existing routing.
5. **No job listings are ever shown anywhere**: grep the frontend (`frontend/components`, `frontend/lib`) and
   backend `api/` surface to confirm there is no listings/apply/save/track UI or `GET/POST /api/jobs` route
   (P6-07/P6-08 both claimed this — re-verify it holds across the whole phase, not just each task's own diff).
6. **Learning-resource corpus is queryable**: a skill-keyed lookup (per P6-06) returns a normalized resource
   for at least one seeded/fixture skill, proving the corpus isn't write-only.

## Acceptance criteria
- [ ] All 6 points above are covered by automated tests (composed/integration-level where prior per-task tests
      only proved pieces in isolation) or a clearly documented manual/live-infra verification for any part that
      genuinely requires a live HF endpoint / live Tavily keys / live Postgres — mirror how P4-10/P5-08
      documented what could and couldn't run live in this environment.
- [ ] **Formatting cleanup**: `ruff format --check .` currently flags drift on files from earlier P6 sub-tasks
      (`app/ingestion/taxonomy_seed.py`, `app/repositories/models/market.py`, `app/tools/tavily_pool.py`,
      `migrations/versions/20260713_0007_market_intelligence.py`, `tests/test_market_models.py`,
      `tests/test_taxonomy_seed.py` — flagged by the P6-07 engineer as pre-existing drift, not yet fixed). Run
      `ruff format .` to fix it and confirm `ruff format --check .` is clean before this task closes (P6-10's
      CI/CD verification depends on this being clean).
- [ ] Full backend test suite green (`ruff check`, `ruff format --check`, `mypy` on `app/`+`migrations/` per CI
      scope, `pytest`).
- [ ] Full frontend test suite green (`lint`, `type-check`, `jest`).
- [ ] Report clearly states: does the current implementation meet the full P6 exit criterion as written
      ("for a target role, the app returns cited, frequency-ranked market requirements... and a skills gap...
      extraction happens once per role, reused across users. No job listings are ever shown.")? If a gap is
      found in any prior P6 task's work, flag it precisely (which task, what's missing) rather than silently
      patching around it, so the orchestrator can route a fix to the right task.

## Design references
- `dev-board/plan.md` — P6 exit criterion  ·  `dev-board/app-design-and-features.md` §5.6, §1.1, §7.4
- Precedent: `dev-board/code-review/P4-10-verify/`, `dev-board/code-review/P5-08-verify/`
