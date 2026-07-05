# Code-reviewer memory index

- [Skeleton/scaffold task checks](check-skeleton-tasks.md) — how to review P0 directory-skeleton tasks against design §8
- [Frontend CI task checks](check-frontend-ci-tasks.md) — how to review frontend/ Next.js CI/Jest setup tasks (workflow + lint/tsc/test); dir renamed from frontend-v2/ in P0-13
- [LLM client/router task checks](check-llm-client-tasks.md) — reviewing backend/app/llm/ tasks: SDK isolation, native tool-calling, error-translation order, mocked-transport tests
- [FastAPI Request[Any] in deps](check-fastapi-request-anno.md) — Request[Any] param breaks Depends() route registration; use bare Request in FastAPI dependencies
- [Alembic migration task checks](check-alembic-migration-tasks.md) — reviewing backend/migrations tasks: DSN single-source, pgvector boundary, no lifespan auto-run, live upgrade/downgrade against the running db container
- [Persistence/rehydration task checks](check-persistence-rehydration-tasks.md) — P2-07+ Postgres-persist + Redis-fallback: the rehydration-not-seeded-back bug (needs a 2-turn post-restart test), best-effort posture, load_history bounds
- [Cross-cutting drift checks](check-cross-cutting-drift.md) — multi-task/audit reviews: app.state key literals, duplicated test fakes, best-effort logging convention, documented deferrals not to re-litigate
