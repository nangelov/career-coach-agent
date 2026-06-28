# Architecture review — P0-07-pgvector · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure (migrations) | `backend/migrations/` reserved for alembic (postgres) | Init SQL placed at `backend/migrations/init/01_enable_pgvector.sql`; an `init/` subfolder separate from Alembic's future `versions/` | None — bounded and non-colliding; Alembic config drops in alongside at P2 |
| A2 | Datastore decision (§4/§11, item 5) | Self-hosted Postgres+pgvector, no managed tier, no Mongo | `pgvector/pgvector:pg16` container; extension enabled via official entrypoint `docker-entrypoint-initdb.d` bind mount | None |
| A3 | Vector dimension (§6 item 3, §7) | `vector(4096)` columns for `kb_chunks`/`user_memories` come via Alembic in P2 | Init SQL enables the extension only; SQL header explicitly defers `vector(4096)` DDL to P2/§7 | None — correctly scoped; no premature coupling to later phase |
| A4 | Phase fit (plan P0 "Local infra: Wire pgvector extension") | Extension wired into local compose stack only | Compose `db` service mounts init dir `:ro`; extension auto-enabled on first init; verified live incl. fresh-volume re-init | None |
| A5 | Budget posture (§11) | Free / OSS / self-hosted | OSS pgvector image, no API, dependency-free dev script reusing existing `asyncpg` dep | None |
| A6 | No secrets in config | Credentials via env/secrets only | Compose uses `${POSTGRES_*}` interpolation; script reads env / local `.env`, nothing hard-coded | None |
| A7 | Dev script location (§8) | §8 has no `scripts/` dir; closest homes are `tests/` (P0-09) | Smoke-test at `backend/scripts/check_pgvector.py`, self-contained (no `app.config` import) | Minor — acceptable as a dev utility; logged as follow-up, not blocking |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — N/A here (infra/init + standalone dev script; no app-layer code touched)
- [x] Honors locked decisions — Postgres+pgvector self-hosted, no managed tier, no Mongo; `vector(4096)` correctly deferred to Alembic (P2). No ReAct/SSO/embeddings surface touched.
- [x] Interfaces-before-implementations — N/A; repositories layer (`repositories/postgres.py`, single shared AsyncEngine pool §6) is not introduced here and is correctly left to later tasks
- [x] Budget posture respected (free/OSS/self-hosted)

## Notes
- **Spaces parity follow-up (not blocking):** the `docker-entrypoint-initdb.d` mechanism only enables the extension in the local `docker-compose` Postgres. The HF Spaces co-located/ephemeral container (§11 line 418 escape-hatch) uses a separate image/path; whoever wires the Spaces DB (or the managed-tier escape hatch) must ensure `CREATE EXTENSION vector` runs there too. Out of scope for P0-07 but worth tracking before any Spaces deploy of the datastore.
- **Script home:** `backend/scripts/` is not in the §8 tree. Keeping the smoke-test self-contained (not importing `app.config`, which would require `HF_API_TOKEN`/`JWT_SECRET_KEY`) is the right call for a host-run DB connectivity check. If a `scripts/` or test-utility convention solidifies in P0-09, consider consolidating then — cheap to relocate, no design debt.
- Init SQL header documenting the "first empty-volume init only" semantics and the P2/§7 DDL boundary is good forward-context hygiene.
