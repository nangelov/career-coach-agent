# Architecture review — P0-03-config · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | config lives at `backend/app/config.py` as pydantic-settings (env, secrets) | Implemented exactly at `backend/app/config.py` using `BaseSettings` + `SettingsConfigDict` | none |
| A2 | Locked #2 (primary LLM) | `zai-org/GLM-5.2` | `LLM_PRIMARY_MODEL` default = `zai-org/GLM-5.2` | none |
| A3 | Locked #4 (failover secondary) | `Qwen/Qwen3.6-27B`, no paid last-resort | `LLM_SECONDARY_MODEL` default = `Qwen/Qwen3.6-27B`; no paid third tier present | none |
| A4 | Locked #3 (embeddings) | `Qwen/Qwen3-Embedding-8B`, in-process, dim 4096 | `EMBEDDING_MODEL` default = `Qwen/Qwen3-Embedding-8B`; docstring notes 4096-dim output | none — pgvector dim is a P1 migration concern, correctly out of scope here |
| A5 | §2 LLM transport (§6.6) | OpenAI-compatible HF Inference base URL behind a single config point | `LLM_BASE_URL` default = `https://api-inference.huggingface.co/v1`; `LLM_TIMEOUT_SECONDS` present for router per-call timeout | none |
| A6 | Locked #9 (datastores) | Postgres + Redis only, self-hosted, no managed tier | `DATABASE_URL` required (asyncpg DSN example), `REDIS_URL` defaults to self-hosted localhost; no Neon/Supabase/Upstash defaults | none |
| A7 | §6.1 auth (SSO-only) | Google + LinkedIn OIDC, backend session JWT, no passwords | `GOOGLE_*` / `LINKEDIN_*` client id+secret, `JWT_SECRET_KEY`/`JWT_ALGORITHM`/`JWT_EXPIRE_MINUTES`; no password fields | none |
| A8 | Locked #5 (guest limits) | 10 messages + 1 upload per guest session | `GUEST_MAX_MESSAGES=10`, `GUEST_MAX_UPLOADS=1` | none |
| A9 | §11 budget / secrets policy | free/OSS/self-hosted; no real secrets in source | Secrets (`HF_API_TOKEN`, `DATABASE_URL`, `JWT_SECRET_KEY`) required via `...`; OAuth secrets default `""`; module docstring states env/HF-Space-Secrets policy | none |
| A10 | Phase fit (P0) | config only, no premature coupling to later phases | Only `pydantic`/`pydantic_settings` imported; no DB driver, LLM client, or LangGraph imports leak in | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — pure config leaf, no cross-layer leak
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only; in-process embeddings) — all four reflected in defaults
- [x] Interfaces-before-implementations — N/A for config; values are named so `LLMClient`/router/repositories can consume them without hardcoding
- [x] Budget posture respected (free/OSS/self-hosted) — self-hosted Redis/Postgres defaults, no managed-tier or paid-model defaults

## Notes
- **Design-clean, no deviations.** Field set matches `task.md` and the locked v2 stack 1:1.
- Follow-up (non-blocking, for the consumers, not this task): `ALLOWED_ORIGINS: list[str]` is read by pydantic-settings from env as a JSON-encoded list — when `api/main.py` CORS wiring lands (P0/P2), document the expected env format so Docker Compose / HF Spaces config sets it correctly. No change required here.
- The module-level `settings = Settings()` import-time instantiation means missing required secrets fail fast at import — correct for the "fail fast on missing secrets" posture; correctness of that behavior is the code-reviewer's call, not a design concern.
- Vector dim (4096) correctly deferred to P1 migrations (locked #3); this task only carries the model id, which is right.
