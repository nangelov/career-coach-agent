# Architecture review — P0-02-pyproject-uv · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 location | Backend deps declared in `backend/pyproject.toml` (uv-managed), not root `requirements.txt` | `backend/pyproject.toml` is the v2 source of truth; full `[project]` + tooling config present | none |
| A2 | §2 / §6.1 orchestration | LangGraph (hand-rolled rejected) | `langgraph>=0.1.0` present; no bespoke-orchestrator deps | none |
| A3 | §6 item 2 primary LLM | GLM-5.2 via HF OpenAI-compatible endpoint (native tool-calling) | `openai>=1.12.0` present (the OpenAI-compatible client) | none — model id is config (P0-03), not a dep |
| A4 | §6 item 3 / §11 embeddings | `Qwen/Qwen3-Embedding-8B` in-process via sentence-transformers, no API cost | `sentence-transformers>=3.0.0` present; no hosted-embedding client | none |
| A5 | §6.7 teachable memory | LangMem in-process over pgvector (supersedes custom recall/learn) | `langmem>=0.0.1` present; no hand-rolled memory libs | none |
| A6 | §4 / §6 item 5 datastores | Postgres (pgvector + JSONB) + Redis only, self-hosted; **no MongoDB**, no managed tier | `sqlalchemy`, `alembic`, `asyncpg`, `pgvector`, `redis` present; **no pymongo / motor / managed-tier SDKs** | none |
| A7 | §6.2 / §7.1 auth | SSO-only (Google + LinkedIn OIDC) via Authlib, backend session, no passwords | `authlib>=1.3.0` + `httpx>=0.27.0` (OIDC flows) present; no passlib/bcrypt | none |
| A8 | §5.3 background jobs | Celery (Redis broker) for async OCR/doc-intel/crawl | `celery[redis]>=5.3.0` present | none |
| A9 | §5.1 ingestion | docling as primary `DocumentParser` engine (+ Pillow for images) | `docling>=2.0.0`, `Pillow>=10.0.0` present | none |
| A10 | §2 PDF output | reportlab kept | `reportlab>=4.0.0` present | none |
| A11 | §11 budget posture | free / OSS / self-hosted; no paid tier | all deps OSS/self-hosted; SerpApi (`google-search-results`) is the pre-existing v1 search dep, opt-in behind a key | none |
| A12 | Phase fit (P0) | Config-only skeleton; no premature coupling to later phases | pure `pyproject.toml` + tooling config, no Python logic | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — config-only task, deps placed in `backend/pyproject.toml`; no layer-violating code introduced
- [x] Honors locked decisions (LangGraph; no ReAct parser deps; Postgres+Redis only — no Mongo/managed-tier SDK; SSO-only via Authlib; in-process sentence-transformers embeddings; LangMem; Celery; GLM via openai-compatible client)
- [x] Interfaces-before-implementations — N/A for a dependency manifest; the seams (`DocumentParser`, `LLMClient`, repositories) are enabled by having docling/openai/sqlalchemy available without binding to them
- [x] Budget posture respected (free/OSS/self-hosted throughout)

## Notes
- **`requirements.txt` retention accepted (not a deviation).** The plan's "don't migrate in place — stand up `backend/` alongside v1, cut over once parity is reached, then delete v1" guidance means the root `requirements.txt` must stay until the v1 root `Dockerfile`/`main.py`/`app.py` are dropped. The acceptance criteria explicitly permits a documented note in lieu of deletion. Logged follow-up: delete root `requirements.txt` in the phase that removes the v1 entrypoints — track so two dependency sources don't drift indefinitely.
- **`google-search-results` vs `serpapi`** is not a design-locked choice (§ does not mandate either); continuity with v1 is a reasonable call. No action.
- **`[tool.ruff.lint].select`** placement (vs the spec's `[tool.ruff].select`) is the correct current ruff idiom for the pinned `ruff>=0.3.0`; an implementation/lint detail, not a design concern — defer to code-reviewer.
- **Vector dimension (4096)** is a migrations concern (P1), out of scope here — flagged only as a forward marker for the alembic/pgvector task.
- `langmem>=0.0.1` is a very loose floor; acceptable for a skeleton (uv lock pins the real version), but worth tightening once the LangMem integration lands (P9-area).
