# Task P6-05-skills-gap — user profile △ role_profile
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullet 6 / plan.md P6 bullet 6: **Skills gap** — user profile △ `role_profile` → the input to
P7's PDP. Design §5.6: *"skills gap = user profile △ role_profile → feeds PDP"*.

Build a pure, testable **service** (e.g. `app/services/skills_gap.py`) that, given a user's structured profile
(`app.ingestion.profile.ProfileSchema.skills: list[str]`, read via `app.services.profile_store.ProfileStore` /
`PostgresProfileStore`) and a target role's cached `RoleProfile.requirements`
(`{skill: {frequency, weight, evidence}}`, read via `app.repositories.market.get_role_profile`), computes:

- **`matched`** — skills the user already has that the role requires (normalized/case-insensitive string
  comparison is sufficient — no embedding/fuzzy-match needed for this task; document that as an explicit
  simplification if you want more, but don't build an ML matcher here).
- **`gap`** — required skills the user's profile does **not** have, each carrying its role-required
  `frequency`/`weight`/`evidence` so the caller can rank/cite it (this is exactly what P7's PDP will consume).
- Order `gap` by descending `frequency`/`weight` (most in-demand missing skills first).

Return a small typed result (Pydantic model in `app/schemas/` or a dataclass, whichever matches the codebase's
existing convention for computed-not-persisted results — check `app/schemas/jobs.py` for the house style) —
not raw dicts — so P6-07's `GET /api/roles/{role}/gap` and P7's PDP agent have a stable contract.

**Handle the "no cached role_profile yet" case explicitly** (a role a user asks about that hasn't been mined):
return a clear "not available yet" outcome (e.g. `gap=None` / a status field) rather than raising, so P6-07 can
decide whether to enqueue mining and degrade gracefully — do not enqueue Celery mining from this service itself
(keep this a pure comparison; P6-07 owns the "trigger a refresh" policy).

## Acceptance criteria
- [ ] `compute_skills_gap(profile_skills, role_requirements) -> SkillsGapResult`-shaped pure function, fully
      unit-tested with plain inputs (no DB/network) — matched/gap partitioning, ordering by frequency/weight,
      case-insensitive matching, empty-profile and empty-requirements edge cases.
- [ ] A thin service wrapper resolves both inputs (profile via `ProfileStore`, role via
      `repositories.market.get_role_profile`) and calls the pure function; unit-tested with fakes for both
      stores, including the "no profile" and "no role_profile yet" cases.
- [ ] No new Celery task, no new migration, no new API route in this task (P6-07 exposes it over HTTP).

## Design references
- dev-board/plan.md: Phase 6, bullet 6  ·  dev-board/app-design-and-features.md §5.6 (last pipeline line +
  "skills gap" paragraphs)
- Reuse: `app/ingestion/profile.py` (`ProfileSchema`), `app/services/profile_store.py` (`ProfileStore`),
  `app/repositories/market.py` (`get_role_profile`), `app/repositories/models/market.py` (`RoleProfile`)

## Constraints / non-goals
- Do not build `GET /api/roles/{role}/gap` here — P6-07 (parallel task) wires this service into that endpoint.
- Do not trigger mining/crawling from here — pure read + compare only.
