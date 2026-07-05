# Architecture review — P2-01-repositories · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | Postgres access lives in `repositories/postgres.py` | `Base`, `PostgresConnectionProvider`, `get_db_session` all in `app/repositories/postgres.py`; exported from `repositories/__init__.py` | none |
| A2 | §4 pooling | Single shared async `AsyncEngine` pool, **max 5 connections**, no per-request connections | One engine built by `from_settings`; `pool_size=POSTGRES_MAX_CONNECTIONS` (default 5) **+ `max_overflow=0`** → hard cap at 5; sessions drawn from the one pool; dependency reads provider off `app.state`, never `create_async_engine` per request | none — `max_overflow=0` is the correct way to make "max 5" a true ceiling |
| A3 | §4 layering (Router→Service→Repo) | Services never touch drivers; DB access confined to repository layer | Engine/driver confined to `postgres.py`; `get_db_session` yields an `AsyncSession` that repositories will consume; no driver leak into services/routers | none |
| A4 | Interfaces-before-implementations | A `Base`/declarative seam future models subclass; provider seam mirroring Redis | Plain SQLAlchemy 2.x `DeclarativeBase` (`Base`) as the single `metadata`/migration target; `PostgresConnectionProvider` mirrors P1-05 `RedisConnectionProvider` lifecycle (`from_settings`/`session()`/`aclose()`) | none — SQLModel-vs-SQLAlchemy choice is design-permitted ("SQLAlchemy/SQLModel"); documented rationale is sound |
| A5 | Locked decision: Postgres (pgvector+JSONB) + Redis only, self-hosted | asyncpg async DSN, no MongoDB, no managed-tier lock-in | `postgresql+asyncpg` DSN from `DATABASE_URL`; no Mongo; DSN-swappable per §4 escape hatch | none — `vector(4096)`/pgvector columns correctly deferred to P2-02..04 |
| A6 | Phase fit / foundation-first | Connection/session foundation only; no table models, no Alembic (P2-02..04) | `Base` maps zero tables (asserted in test); no migrations; lifespan `SELECT 1` as connectivity proof | none — scope boundary respected, no premature coupling |
| A7 | §4 fail-fast posture | Verify data layer reachable at startup | Lifespan builds provider, runs `verify_connectivity()` (`SELECT 1`) fail-fast, disposes on shutdown; replaces the P0 "stubbed (P2)" log lines | none |
| A8 | Budget posture (§11) | Free/OSS/self-hosted, no heavy deps | Uses already-present sqlalchemy/asyncpg; CI test path adds only `aiosqlite`+`greenlet` (light, no torch); no managed tier | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — DB access confined to `repositories/postgres.py`.
- [x] Honors locked decisions — Postgres+Redis only, self-hosted, async driver; no ReAct/SSO/embeddings surface touched.
- [x] Interfaces-before-implementations — `Base` + `PostgresConnectionProvider` seam defined before any table model.
- [x] Budget posture respected (free/OSS/self-hosted).

## Notes
- **Non-blocking follow-up (provider-wiring asymmetry).** Postgres is now built **eagerly** in the lifespan
  (composition root), while Redis is still built **lazily on first request** in `build_chat_service` (P1-05).
  §4 frames both datastores as single shared pools owned at the composition root; the eager Postgres wiring
  is the more design-faithful shape. The engineer correctly left Redis untouched (task constraint: additive,
  don't touch Redis's public surface). Recommend a future task move the `RedisConnectionProvider` to the same
  eager lifespan wiring for symmetry — logged, not gated.
- Shutdown teardown in `main.py` disposes the Postgres pool best-effort and is ordered after chat-service
  close and before Redis close — clean and correct for this phase.
- Real-Postgres integration coverage is deferred to arrive naturally with P2-02..04 tables/migrations; the
  SQLite-plumbing + non-connecting-asyncpg pool-config test split is a reasonable design-conformance proof
  (the cap is dialect-agnostic engine config). This is primarily a code-reviewer concern.
