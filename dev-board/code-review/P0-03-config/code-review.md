# Code review — P0-03-config · engineer revision 1

## Verdict: APPROVED

## Findings

| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | backend/app/config.py:124 | `ALLOWED_ORIGINS: list[str]` is parsed by pydantic-settings from env as **JSON only**. Setting `ALLOWED_ORIGINS=https://app.com,https://b.com` (the natural deploy format) raises `SettingsError` at startup and crashes the app; only `'["https://app.com"]'` JSON works. Verified empirically. | Either add a `field_validator(mode="before")` that splits comma-separated strings into a list, or document in the field/`description` that the env value must be a JSON array. Track for the CORS/HF-Spaces deploy task so prod config doesn't crash on first boot. |
| C2 | nit | backend/app/config.py (whole) | Acceptance criterion #4 cites `python -c "from backend.app.config import settings"`, but there is no `backend/__init__.py`, so that exact import fails from repo root. The engineer correctly used the established repo convention (`cd backend && from app.config import ...`). | None required — flagging that the criterion's literal command is inaccurate, not the code. Real usage path works. |

## Notes

Verified against a clean venv with `pydantic-settings` 2.13 installed:
- `py_compile` passes; no lines exceed 100 chars.
- Defaults load correctly (`LLM_PRIMARY_MODEL=zai-org/GLM-5.2`, `ALLOWED_ORIGINS=['http://localhost:3000']`, `DEBUG=False`) when the three required fields are supplied.
- Missing `HF_API_TOKEN` / `DATABASE_URL` / `JWT_SECRET_KEY` raises a clear pydantic `ValidationError` naming each missing field (fail-fast confirmed).
- `case_sensitive=False` works: lowercase env names (`hf_api_token`, `debug=true`) resolve and coerce correctly.
- Required secrets use `Field(...)` (no default); OAuth/SerpAPI/Rapid keys default to `""` so the app boots guest-only without SSO — matches the locked guest-mode + SSO-only decisions.
- Non-secret defaults match the locked v2 decisions (GLM-5.2 / Qwen3.6-27B / Qwen3-Embedding-8B / HF OpenAI-compatible base URL / guest limits 10+1).

Security:
- No secrets hardcoded. `git ls-files` shows no `.env` tracked; both `.env` and `backend/.env` are git-ignored (`git check-ignore` confirms). `backend/` is entirely untracked (P0 work-in-progress), so nothing sensitive is staged.
- Module docstring states the secrets policy and the `backend/.env` location — matches the task constraint.

All six acceptance criteria are met (criterion #4's literal command caveat is C2 — a wording issue in the criterion, not a code defect). The single behavioral footgun (C1) is minor: the default works and the field type was specified by the task; it only bites on a specific env-override format and is fixable in the deploy/CORS task.
