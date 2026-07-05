# Task CR-01-design-practices-audit — Whole-codebase Main Software Design Practices check
- **Phase:** cross-cutting (post-P2)   **Status:** REVIEW   **Tags:** (D)

## Scope
User-requested, ad-hoc `[CODE_REVIEW]`: after P2 completion, audit the **entire codebase built so far**
(P0 + P1 + P2 — `backend/app/`, `backend/migrations/`, `backend/tests/`, and `frontend/` where applicable)
for adherence to **main software design practices/principles**, independent of any single task's acceptance
criteria. This is a holistic quality pass across everything shipped, not a re-review of any one task.

Check for (non-exhaustive, use professional judgment):
- **SOLID** — single responsibility, open/closed, Liskov substitution, interface segregation, dependency
  inversion (ports-and-adapters boundaries: `LLMClient`, `SessionMemory`, `CancelRegistry`, `ConversationStore`,
  `EmbeddingClient`, repositories — are they respected everywhere, or is there a leak of driver/DB code into
  services or API layers?).
- **DRY** — duplicated logic across modules/tasks that should be extracted/shared (e.g. repeated
  get-or-create patterns, repeated best-effort-persist-and-log-failure patterns, repeated pgvector query
  shapes).
- **Separation of concerns / layering** — Router → Service → Agent/Repository, as mandated by
  `dev-board/app-design-and-features.md` §8 and the cross-cutting definition-of-done in `dev-board/tasks.md`
  ("Every endpoint flows Router → Service → (Agent/Repository); no driver access in services").
- **Consistency** — naming conventions, error-handling patterns, logging patterns, test structure/fixtures
  consistent across P0/P1/P2 tasks (each built by a fresh engineer dispatch — check for drift).
- **Cohesion / module boundaries** — are `app/repositories/models/` growing sanely (identity.py, knowledge.py,
  structured module)? Is `app/repositories/postgres.py` still a clean foundation, or has logic leaked in that
  belongs in adapters?
- **Testability** — dependency injection used consistently (FastAPI `Depends`, injectable fakes for
  LLM/embeddings), no hidden global state reintroduced (the whole point of leaving v1's global
  `ConversationBufferMemory` behind).
- **Config/secrets hygiene** — all config via `app/config.py` pydantic-settings, no hardcoded values/secrets.
- **Error handling & resilience** — consistent best-effort-vs-fail-hard posture (e.g. persistence failures
  logged and swallowed vs. genuine errors surfaced), no silent failure of user-facing behavior.
- Anything else clearly violating a "main software design practice" (e.g. God objects, tight coupling,
  missing abstractions that will bite in P3+, inconsistent async patterns).

## Acceptance criteria
- [ ] Every finding is filed with a concrete file:line reference and a clear required change — not vague
      generalities.
- [ ] Findings are triaged by severity (blocker/major/minor/nit) per the standard verdict gate.
- [ ] The review explicitly covers backend `app/` (api, services, repositories, llm, schemas, tasks) and the
      migrations/tests directories; note if frontend is in/out of scope given P2 was backend-only.
- [ ] Verdict line present: `APPROVED` (no blocker/major issues) or `CHANGES_REQUESTED` (blocker/major
      findings needing an engineer fix pass).

## Design references
- dev-board/app-design-and-features.md — full document (architecture, §8 structure, layering).
- dev-board/plan.md — phased scope, so findings are weighed against what's actually supposed to exist yet
  (don't flag P3+ features as "missing").
- dev-board/tasks.md — cross-cutting / definition-of-done section.
- All prior `dev-board/code-review/P0-*`, `P1-*`, `P2-*` `engineer.md` files as historical context for why
  patterns were chosen (avoid re-litigating decisions already made and blessed unless they're genuinely
  problematic).

## Constraints / non-goals
- This is a **review-only** pass (no engineer dispatched yet). If findings warrant fixes, the orchestrator
  will route them to the fullstack-engineer in a follow-up revision, per the standard fix loop.
- Do not propose scope for future phases (P3+) — flag only what's wrong with what's already built.
- Both **code-reviewer** and **system-architect** review in parallel, per the standard pipeline, since this
  spans both correctness/quality concerns and design-conformance concerns.
