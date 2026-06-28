# Task P0-03-config — app/config.py with pydantic-settings

- **Phase:** P0   **Status:** ENG   **Tags:** (B)

## Scope

Implement `backend/app/config.py` using **pydantic-settings** (`BaseSettings`). This is the single
source of truth for all runtime configuration and secrets — all values come from environment variables
or HF Space Secrets; **no defaults that contain real secrets, and no secrets committed to source**.

The `Settings` class must cover every secret / config knob the v2 system will need:

### LLM / HF Inference
- `HF_API_TOKEN: str` — HuggingFace API token (was `HUGGINGFACEHUB_API_TOKEN` in v1)
- `LLM_PRIMARY_MODEL: str = "zai-org/GLM-5.2"` — primary model id
- `LLM_SECONDARY_MODEL: str = "Qwen/Qwen3.6-27B"` — failover model id
- `LLM_BASE_URL: str = "https://api-inference.huggingface.co/v1"` — OpenAI-compatible base URL
- `LLM_TIMEOUT_SECONDS: int = 30`
- `EMBEDDING_MODEL: str = "Qwen/Qwen3-Embedding-8B"`

### Datastores
- `DATABASE_URL: str` — async Postgres DSN (e.g. `postgresql+asyncpg://...`)
- `REDIS_URL: str = "redis://localhost:6379/0"`

### Auth / SSO
- `JWT_SECRET_KEY: str` — signing key for backend session JWTs
- `JWT_ALGORITHM: str = "HS256"`
- `JWT_EXPIRE_MINUTES: int = 60`
- `GOOGLE_CLIENT_ID: str = ""`
- `GOOGLE_CLIENT_SECRET: str = ""`
- `LINKEDIN_CLIENT_ID: str = ""`
- `LINKEDIN_CLIENT_SECRET: str = ""`

### External APIs
- `SERPAPI_API_KEY: str = ""` — Google Jobs / web search
- `RAPID_API_KEY: str = ""`

### App behaviour
- `DEBUG: bool = False`
- `ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]`
- `GUEST_MAX_MESSAGES: int = 10`
- `GUEST_MAX_UPLOADS: int = 1`

### pydantic-settings wiring
- Use `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)`
- Export a module-level singleton: `settings = Settings()`
- Add a brief module docstring explaining that secrets must come from env / HF Space Secrets, never committed.

### Stubs to update
- Replace the comment-only stub in `backend/app/config.py` left from P0-01 with the real implementation.

## Acceptance criteria

- [ ] `backend/app/config.py` contains a `Settings(BaseSettings)` class with all fields listed above
- [ ] Module-level `settings = Settings()` singleton exported
- [ ] `model_config` reads from `.env` file with `case_sensitive=False`
- [ ] `python -c "from backend.app.config import settings; print(settings.LLM_PRIMARY_MODEL)"` prints the default without crashing (fields with defaults work; required fields without defaults raise a clear validation error)
- [ ] No real secret values are hardcoded (empty string or no default for secrets; descriptive defaults only for non-sensitive config)
- [ ] Module docstring present explaining secrets policy

## Design references

- `dev-board/app-design-and-features.md`: §2 Tech Stack, §6 Decisions (§6.1 auth, §6.6 LLM router), §8 Target Project Structure
- `dev-board/plan.md`: Phase 0

## Constraints / non-goals

- Do NOT implement any other module — only `backend/app/config.py`
- Do NOT commit or log any real secret values
- Keep `DATABASE_URL` required (no default) — forces explicit config in every environment
- Keep `JWT_SECRET_KEY` required (no default) — forces explicit config
- `HF_API_TOKEN` required (no default) — forces explicit config
- The `.env` file already exists at repo root with v1 secrets; do not delete it, but note in the docstring that the v2 `.env` belongs at `backend/.env` (or root) and must not be committed
