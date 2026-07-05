# Architecture review — FIX-01-backend-test-deps · engineer revision 1

## Verdict: APPROVED

Design conclusion is sound and matches locked intent. The core question the orchestrator posed —
"is *integration tests never run in CI, only locally* an acceptable permanent state, or a real gap?" —
resolves to: **it is the design-intended state for now, correctly deferred, and the engineer's decision to
flag-not-implement the CI service container is the right scope call.** See A4/A5 and Notes N1.

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / layering | CI+build config only; no Router→Service→Repo perturbation | Changes limited to `.github/workflows/backend-ci.yml`, `backend/Makefile`, `conftest.py` import spacing. No source/layer changes | None |
| A2 | Locked stack: Postgres + **pgvector** (`vector(4096)`) — plan §213 #2/#3 | pgvector client lib is a genuinely-required import (`repositories/models/knowledge.py:62`), pulled transitively via `repositories/__init__`; must be installable at collection | `pgvector` added to curated install (CI + Makefile). Lazy/guarded-import alternative correctly rejected (would diverge test-time from prod-time, hide a real dep) | None — conformant; import posture matches P0-09's "list required-but-light libs explicitly" |
| A3 | Budget posture §11 (free/OSS/self-hosted) | Curated light install; no heavy ML/CUDA in CI | pgvector is pure-Python (no torch/CUDA); light-install posture preserved. Matches P0-09 blessed A6 | None |
| A4 | P0-09 scope: **live-DB integration deferred out of CI** (P0-09 task.md non-goals: "No integration tests against a live DB/Redis … Do not run docker compose in CI") | 40 skips are a single live-Postgres integration gate; skip-not-fail without a reachable DB; covered via `make test-integration` (142 passed) | Matches the **explicit** P0-09 non-goal and blessed A6/N1 free-tier posture exactly. "Expected-by-design" classification is correct, not a papering-over | None — conclusion validated against design |
| A5 | Phase fit / YAGNI — minimal regression fix, not a CI redesign | Fix the collection-error root cause; don't prematurely couple to a CI-DB-service decision | CI Postgres service container flagged as a follow-up, not bundled. Correct: adding a pgvector-enabled `services:` image + `alembic upgrade head` + `DATABASE_URL` is a deliberate scope expansion, better decided on its own | None — proportionate scope; see N1 for the framing nuance |
| A6 | DRY (curated install list) | Single source of truth for what CI/local installs | List is **duplicated** verbatim in `backend-ci.yml` and `Makefile install`; this drift is the *root cause* of this very bug class. Engineer synced both and acknowledged the smell | Non-blocking. Logged follow-up N2 — cheap to unwind now, expensive-to-diagnose later |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — config-only change, layering untouched.
- [x] Honors locked decisions — pgvector/Postgres stack reinforced; no ReAct parser / Mongo / SSO surface touched.
- [x] Interfaces-before-implementations — N/A (no new seams); repository/models seams unchanged.
- [x] Budget posture respected — pure-Python client only; no ML/CUDA pulled into CI.

## Notes

**N1 (the orchestrator's core question — budget framing nuance, not a blocker).** "Integration tests never
run in CI" is the *design-intended* state per P0-09's explicit non-goal and the §11 free-tier posture, and
deferring it here is correct. One caveat on the *justification*: the engineer (and P0-09) lean on "free-tier
posture / no service containers" as the reason. GitHub-hosted runners provide Postgres **`services:`
containers at no extra cost** — so this coverage is *not* budget-blocked; it's blocked only by scope
(needs a pgvector-enabled image + migration run + `DATABASE_URL` wiring). This distinction matters for the
follow-up: it should be framed as a deliberate "do we want live-DB coverage in CI?" decision, **not** as
"budget forbids it." As a permanent state, integration coverage living only behind `make test-integration`
is acceptable *if* contributors reliably run it, but it leaves P2 persistence / pgvector / migration paths
unguarded on PRs — a real (if presently-accepted) coverage risk. Recommend a scoped follow-up task to add
the CI Postgres service, tracked against the P2 exit / P3 work rather than this fix. The engineer's decision
to flag-not-implement here is the correct call for this task.

**N2 (DRY follow-up — A6).** The curated dependency list now lives in two places (`backend-ci.yml` and
`Makefile install`) and drifting between them is exactly what caused this incident. `backend/pyproject.toml`
already uses `[dependency-groups]` (e.g. `dev`); a `ci-runtime` group referenced by both CI and the Makefile
would give a single source of truth and structurally prevent recurrence. Cheap to unwind; out of scope for a
minimal regression fix, but worth logging.

**N3 (conftest import-spacing restore).** Restoring the blank line after `from __future__ import annotations`
to satisfy ruff `I001` is a pure-formatting fix to a stray working-tree edit, not a test weakening — no design
concern.
