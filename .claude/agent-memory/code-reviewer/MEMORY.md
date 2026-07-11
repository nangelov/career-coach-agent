# Code-reviewer memory index

- [Skeleton/scaffold task checks](check-skeleton-tasks.md) — how to review P0 directory-skeleton tasks against design §8
- [Frontend CI task checks](check-frontend-ci-tasks.md) — how to review frontend/ Next.js CI/Jest setup tasks (workflow + lint/tsc/test); dir renamed from frontend-v2/ in P0-13
- [LLM client/router task checks](check-llm-client-tasks.md) — reviewing backend/app/llm/ tasks: SDK isolation, native tool-calling, error-translation order, mocked-transport tests
- [FastAPI Request[Any] in deps](check-fastapi-request-anno.md) — Request[Any] param breaks Depends() route registration; use bare Request in FastAPI dependencies
- [Alembic migration task checks](check-alembic-migration-tasks.md) — reviewing backend/migrations tasks: DSN single-source, pgvector boundary, no lifespan auto-run, live upgrade/downgrade against the running db container
- [CI Postgres service-container task checks](check-ci-service-container-tasks.md) — reviewing GHA `services:` Postgres+pgvector tasks: reproduce fresh-container CI flow, mypy-strict regression from adding alembic, install-list sync, secrets posture, isolation
- [Persistence/rehydration task checks](check-persistence-rehydration-tasks.md) — P2-07+ Postgres-persist + Redis-fallback: the rehydration-not-seeded-back bug (needs a 2-turn post-restart test), best-effort posture, load_history bounds
- [Cross-cutting drift checks](check-cross-cutting-drift.md) — multi-task/audit reviews: app.state key literals, duplicated test fakes, best-effort logging convention, documented deferrals not to re-litigate
- [Auth/session-JWT task checks](check-auth-session-jwt-tasks.md) — reviewing P3 auth tasks: joserfc token-codec security (alg-pin, exp-essential, typed claims), guest-creation abuse gap, session store layering
- [LangGraph state/graph task checks](check-langgraph-state-tasks.md) — reviewing P4 agents/ typed-state + reducer tasks: verify reducer honored under real StateGraph fan-out (PEP563 gotcha), StrEnum-key safety, JSON round-trip
- [Backend diff-vs-report reconcile](check-backend-diff-vs-report.md) — reconcile engineer.md "Files changed" vs actual git diff: unmentioned uv.lock churn, zero-diff "restores", overstated pre-existing structure
- [Phase-exit verification task checks](check-phase-exit-verification-tasks.md) — reviewing P*-NN-verify tasks: discriminating streaming/citation/guardrail-spy assertions + confirm bundled "mechanical" reformats are truly zero-logic
- [Curated CI venv mypy](project-curated-ci-venv-mypy.md) — CI mypy runs against a narrow curated venv, not full dev venv; reproduce there + verify each fix load-bearing (find_spec present/absent)
