# Engineer report — P6-05-skills-gap · Revision 1

## Summary
Skills-gap analysis (design §5.6: *"skills gap = user profile △ role_profile → feeds PDP"*) —
the last line of the market pipeline and P7's PDP input. Two layers so the arithmetic is DB/network-free:
a **pure diff** `compute_skills_gap(...)` and a **thin `SkillsGapService`** that resolves the two inputs
(profile via `ProfileStore`, role via `repositories.market.get_role_profile`) and degrades gracefully.
No API route, no Celery task, no migration (all P6-07 / out of scope).

## Files changed
- `app/schemas/skills_gap.py` (new) — typed contract: `SkillGap` (missing skill + role-required
  frequency/weight/evidence), `SkillsGapResult` (matched + ordered gap + `status`), `SkillsGapStatus`
  literal. House style mirrors `app/schemas/jobs.py`; independent of the ingestion/agent layers.
- `app/services/skills_gap.py` (new) — pure `compute_skills_gap` + `SkillsGapService`; local
  structural `SessionProvider` Protocol.
- `tests/test_skills_gap.py` (new) — 8 pure-function tests + 3 service tests (fakes only).

## Key decisions
- **Pure vs. wrapper split** (acceptance criteria): `compute_skills_gap` is I/O-free and always
  returns `status="ok"`; availability is the wrapper's concern. Fully unit-tested with plain inputs.
- **Graceful degradation over raising** (task): the service returns `status="profile_missing"` (no
  parsed profile — checked first, DB untouched) or `"role_profile_missing"` (role never mined),
  each with `gap=None`, so P6-07 owns the "enqueue mining / prompt CV upload" policy. This service
  never triggers mining (§5.6 — pure read + compare).
- **Matched keyed by the role's requirement name**, not the CV spelling, so the contract speaks one
  vocabulary. Matching is normalized case-insensitive (`strip().lower()`) — documented simplification,
  no embedding/fuzzy matcher (task said not to build one).
- **Gap ordering** = descending frequency, then weight, then skill name (stable deterministic tie-break)
  — most in-demand missing skills first (task).
- **Defensive JSONB parsing** (§5.1 graceful degradation): bad/absent `frequency`/`weight` → `0.0`,
  non-list `evidence` (e.g. a stray string) → `[]`, non-dict requirement spec → treated as empty.
- **Layering**: service depends only on ports (`ProfileStore` + a local `SessionProvider` Protocol) and
  the `repositories.market.get_role_profile` helper — no SQLAlchemy in the service body, no import from
  the agents layer. Local `SessionProvider` (not imported from `agents.rag_agent`) keeps service→agent
  layering clean; it is a 2-line structural Protocol.

## How to verify
- `.venv/bin/pytest tests/test_skills_gap.py -q`
- `.venv/bin/ruff check app/schemas/skills_gap.py app/services/skills_gap.py tests/test_skills_gap.py`
- `.venv/bin/mypy app/schemas/skills_gap.py app/services/skills_gap.py`

## Tests (final step — mandatory)
- `.venv/bin/pytest -q` → **561 passed, 57 skipped** (11 new; skips = live-DB/ML, unchanged). No failures.
- `ruff check` + `ruff format --check` → All checks passed / already formatted.
- `mypy app/schemas/skills_gap.py app/services/skills_gap.py` → Success, no issues.

## Self-check
- [x] Meets acceptance criteria: pure `compute_skills_gap` unit-tested (matched/gap partition, freq/weight
      ordering, case-insensitive matching, empty-profile/empty-requirements/malformed edges); thin wrapper
      unit-tested with fakes incl. no-profile + no-role_profile cases; no new Celery task/migration/route.
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (DB read via `repositories.market`,
      service off the driver; typed result, not raw dict).
- [x] Tests/lints pass (pasted above).
