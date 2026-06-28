# Engineer report — P0-03-config · Revision 1

## Summary

Replaced the comment-only stub in `backend/app/config.py` with a full `pydantic-settings`
`BaseSettings` implementation covering all v2 configuration fields.  The module is the single
source of truth for runtime config and secrets; a module-level `settings = Settings()` singleton
is exported for use everywhere in the backend.

## Files changed

- `backend/app/config.py` — full implementation (was a one-line comment stub from P0-01)

## Key decisions

1. **Required fields use `Field(...)` (Ellipsis), no default** — `HF_API_TOKEN`, `DATABASE_URL`,
   and `JWT_SECRET_KEY` are intentionally required.  Any environment missing them gets a clear
   `ValidationError` at startup rather than running with a silent empty/wrong value.  This follows
   the task constraint and the general "fail fast on missing secrets" policy.

2. **`case_sensitive=False` in `SettingsConfigDict`** — allows env vars to be set as
   `HF_API_TOKEN` or `hf_api_token` (common in Docker Compose / HF Spaces), matching the
   task spec exactly.

3. **`env_file=".env"` is relative** — pydantic-settings resolves it from the process CWD,
   which is `backend/` when the app runs from that directory.  The docstring makes explicit
   that the v2 `.env` belongs at `backend/.env` (or the repo root) and must not be committed.
   The existing v1 `.env` at the repo root is untouched.

4. **`ALLOWED_ORIGINS: list[str]`** — uses `list[str]` (PEP 585 modern union syntax) rather
   than `List[str]` from `typing`, consistent with the `target-version = "py311"` ruff setting
   and the UP rule set.

5. **All non-secret defaults match the locked v2 decisions** — `LLM_PRIMARY_MODEL` =
   `zai-org/GLM-5.2`, `LLM_SECONDARY_MODEL` = `Qwen/Qwen3.6-27B`, `EMBEDDING_MODEL` =
   `Qwen/Qwen3-Embedding-8B`, `LLM_BASE_URL` = HF OpenAI-compatible endpoint — all matching
   §2 / §6.6 of `app-design-and-features.md`.

6. **OAuth client secrets default to `""`** — Google and LinkedIn client secrets have empty
   string defaults so the app starts in guest-only mode without SSO credentials, rather than
   failing at startup.  The docstring notes they must be injected via HF Space Secrets for
   production.

## How to verify

```bash
# 1. Syntax check (no project deps required)
python3 -m py_compile backend/app/config.py && echo "OK"

# 2. Functional check — defaults only (requires pydantic-settings in the venv)
#    Set required fields so validation passes:
HF_API_TOKEN=test DATABASE_URL=postgresql+asyncpg://u:p@localhost/db JWT_SECRET_KEY=secret \
  python -c "
import sys; sys.path.insert(0, 'backend')
from app.config import settings
print('LLM_PRIMARY_MODEL:', settings.LLM_PRIMARY_MODEL)
print('LLM_SECONDARY_MODEL:', settings.LLM_SECONDARY_MODEL)
print('EMBEDDING_MODEL:', settings.EMBEDDING_MODEL)
print('GUEST_MAX_MESSAGES:', settings.GUEST_MAX_MESSAGES)
print('DEBUG:', settings.DEBUG)
"

# 3. Missing required field raises a clear error:
python -c "
import sys; sys.path.insert(0, 'backend')
import os; os.environ.pop('HF_API_TOKEN', None)
from app.config import settings
" 2>&1 | grep -i "hf_api_token\|validation"

# 4. Line-length (manual ruff proxy — no lines exceed 100 chars):
awk 'length > 100 {print NR": "length" chars: "$0}' backend/app/config.py
# (expected: no output)
```

## Self-check

- [x] Meets acceptance criteria
  - `Settings(BaseSettings)` with all fields listed in task.md
  - Module-level `settings = Settings()` singleton exported
  - `model_config` reads from `.env` with `case_sensitive=False`
  - Fields with defaults work; required fields raise `ValidationError`
  - No real secret values hardcoded (required fields have `...`; OAuth secrets default to `""`)
  - Module docstring present explaining secrets policy
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (config layer only)
- [x] `py_compile` passes — syntax OK
- [x] No lines exceed 100 chars (verified with `awk`)
- [x] Imports: only `pydantic.Field` and `pydantic_settings` — no unused imports (F rule)
- [x] `list[str]` not `List[str]` — passes UP rule for py311 target
