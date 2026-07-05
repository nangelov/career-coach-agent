# Architecture review — P2-09-integration-verify · engineer revision 1

## Verdict: APPROVED

The orchestrator's core question — *is a Makefile-only local verification workflow the right scope, or should
this have touched CI/docs?* — resolves cleanly: **Makefile-only is the correct, design-intended scope.** Live-DB
integration coverage being deferred out of CI and living behind `make test-integration` is a **blessed, ratified
posture** (P0-09 non-goals + FIX-01 arch-review A4/A5). This task formalizes the *local* lifecycle only, exactly
as its own `task.md` constrains, and does not perturb any product layer. The one real defect (the documented
`make migrate` step could not load its env standalone) was correctly root-caused and fixed in tooling.

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure / layering | Tooling-only change; no Router→Service→Repo perturbation | Sole change is `backend/Makefile` (`COMPOSE`, `LIVE_DB_ENV`, `migrate-integration`, `test-integration-full`, refactored `test-integration`, comment fixes, `.PHONY`). No source/schema/migration/compose edits | None |
| A2 | Locked stack: self-hosted Postgres(pgvector)+Redis via docker-compose (plan §213 #2/#6) | Verification drives the real compose `db` service (`pgvector/pgvector:pg16`), not a mock; `vector(4096)` paths exercised via the 6 live-DB suites | `test-integration-full` = `up -d --wait db → migrate-integration → test-integration → down`; 40 previously-skipped tests now execute + pass (142/0). Uses the actual locked stack | None |
| A3 | CI posture — live-DB integration **deferred out of CI**, skip-not-fail (P0-09 non-goals; FIX-01 A4) | No `services:` Postgres added to `backend-ci.yml`; local Makefile is the integration surface | No CI change; explicitly flagged out of scope per `task.md`, matching the blessed ruling. DB-less `make test` still skips cleanly (102/40) | None — correct scope call, consistent with prior ratification |
| A4 | Phase fit / YAGNI — (T) verification task, not a redesign | Formalize the ad-hoc FIX-01 run into a repeatable target; fix only genuine failures | Exactly that. One genuine defect (`make migrate` env loading) fixed; no tests weakened, no skip markers added | None |
| A5 | Budget posture §11 (free/OSS/self-hosted) | No paid/managed tier; local docker-compose only | Uses the free self-hosted compose stack; `down` preserves named volumes (no re-provision cost). No ML/CUDA pulled | None |
| A6 | DRY / SoC | No duplicated env/DSN derivation across recipes | `LIVE_DB_ENV` consolidates the sourcing+DSN logic reused by `migrate-integration` and `test-integration` (was inline in one) — a net DRY *improvement* over the prior state | None |
| A7 | Docs placement | Reproducible sequence captured where contributors are directed | Documented in the Makefile (CLAUDE.md + FIX-01 both route contributors to `make`); root `README.md` left untouched as it is still v1-oriented (CRA / `pip install`). `task.md` offered "README/Makefile" | None — correct call; see N2 |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — tooling-only; no layer touched.
- [x] Honors locked decisions — self-hosted Postgres(pgvector)+Redis via docker-compose reinforced; no Mongo / managed tier / ReAct parser / SSO surface touched.
- [x] Interfaces-before-implementations — N/A (no new seams).
- [x] Budget posture respected — free/OSS/self-hosted; no paid infra, no heavy ML in the path.

## Notes

**N1 (volume-persistence behavior is consistent with the compose design — with one documented edge).** The
engineer's reasoning is correct: `docker compose down` (no `-v`) preserves `postgres_data`, so the pgvector
extension (enabled once by `backend/migrations/init/01_enable_pgvector.sql`, which the Postgres entrypoint runs
**only on first cluster init / empty volume**) and the schema survive a re-`up` with no re-migration. This
matches the compose file's own comment (lines 21-24) and the intended local dev lifecycle. **Edge worth
flagging for the next person:** `task.md` says to repeat this "whenever the container/Postgres/**pgvector
setup**... changes." Because `down` keeps the volume, a change to the *init script itself* (pgvector setup)
will **not** re-run on the next `up` — that specific case requires `docker compose down -v` (or a fresh
volume) to truly re-verify the from-empty init path. The common cases (`schema/migration/test` changes) are
fully handled, since `migrate-integration` (`alembic upgrade head`) applies against the persisted volume. Not a
blocker: the pgvector init is a stable, locked one-time setup unlikely to churn, and volume-preserving `down`
is the right *default* (fast, non-destructive). A one-line comment noting "use `down -v` if you change the
init script" would close the gap; logged as a cheap follow-up, not a required change.

**N2 (docs placement — accepted, with the standing follow-up unchanged).** Keeping the workflow in the
Makefile rather than the v1 root README is the right call for now. The broader "v2 README / contributor docs"
gap remains a separate future task and is untouched here — correctly.

**N3 (CI coverage risk — unchanged standing follow-up, not this task's job).** As noted in FIX-01 N1: P2
persistence / pgvector / migration paths remain unguarded on PRs until a CI Postgres `services:` container
lands. This is a *deliberate scope deferral*, not budget-blocked (GitHub-hosted runners provide Postgres
service containers at no cost). This task explicitly and correctly does not address it; recommend the CI
service-container follow-up continue to be tracked against P2-exit / P3, not bundled here.
