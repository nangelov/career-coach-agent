# Task P2-09-integration-verify — Full integration verification against a live container

- **Phase:** P2   **Status:** ENG   **Tags:** (T)

## Scope
`dev-board/tasks.md` (P2 section) now has this item:

> Full integration verification against a live container: `docker compose up -d db` (Postgres+pgvector) →
> run the full backend test suite so the live-DB-gated integration tests execute instead of skipping
> (`make test-integration` or equivalent) → confirm green → `docker compose down` to tear the container
> back down. Repeat this whenever the container/Postgres/pgvector setup or schema changes.

Context: `FIX-01-backend-test-deps` (see `dev-board/code-review/FIX-01-backend-test-deps/`) already
established that ~40 tests in `backend/tests/` are gated on a live Postgres connection and skip
(`"Postgres not reachable at DATABASE_URL — integration test skipped"`) when one isn't reachable, and that
`make test-integration` runs them against docker-compose Postgres. That was verified once, ad hoc, during
that bugfix. This task turns it into a proper, repeatable, checked-off verification:

1. Bring up the Postgres(+pgvector) container via `docker compose up -d db` (or whatever the correct
   compose service name / minimal set is — check `docker-compose.yml`).
2. Ensure schema is current (`alembic upgrade head` / `make migrate` — whatever the documented command is).
3. Run the full backend test suite (`make test-integration` or equivalent) and confirm the previously-skipped
   integration tests (`test_conversation_store`, `test_identity_models`, `test_knowledge_models`,
   `test_p2_exit_verification`, `test_structured_models`, `test_vector_search`, and any others gated the same
   way) now **execute and pass** rather than skip.
4. Tear the container back down (`docker compose down`) afterwards, confirming the workflow is clean and
   repeatable (no leftover volumes/state required beyond what's already documented).
5. If anything fails once actually running against Postgres (not just skipping), fix the root cause —
   whether it's in the app code, the test, the migration, or the docker-compose config.
6. Make this reproducible for the next person: document the exact command sequence (README/Makefile —
   check if `make test-integration` already does all of steps 1–4, or if some of it is manual and should be
   captured in a Makefile target).

## Acceptance criteria
- [ ] Documented, reproducible command sequence exists to: start the Postgres+pgvector container, migrate,
      run the integration test suite, and tear the container down.
- [ ] Running that sequence now produces the previously-skipped tests actually executing (not skipping) and
      passing.
- [ ] Any genuine failures uncovered while actually running against Postgres are root-caused and fixed.
- [ ] `engineer.md` documents the before/after test counts (e.g. "102 passed, 40 skipped" locally without a
      DB vs. "142 passed, 0 skipped" with the container up) as proof.

## Design references
- dev-board/plan.md: P2 — Persistence foundation & repositories (exit criteria: "vector insert + similarity
  query verified").
- `dev-board/code-review/FIX-01-backend-test-deps/engineer.md` — prior finding that all 40 skips are a
  legitimate live-Postgres gate, proven via one ad hoc `make test-integration` run.
- `docker-compose.yml`, `backend/Makefile`.

## Constraints / non-goals
- This is a **local/manual verification workflow**, not a new CI service container — do not add a Postgres
  `services:` block to `.github/workflows/backend-ci.yml` as part of this task (that was flagged as a
  separate, larger follow-up in the architecture review of FIX-01; out of scope here unless trivial and
  explicitly noted).
- Do not weaken or delete tests, and do not add skip markers to dodge a real failure.
- Per the agent-handoff skill: running the test suite and fixing root causes of failures is a mandatory
  final step, same as every other task — this task IS that step, formalized and repeated.
