# Task FIX-06-ruff-format-check — Backend CI failing on `ruff format --check`
- **Phase:** cross-cutting   **Status:** ENG   **Tags:** (I)

## Scope
`dev-board/failed_pipeline.log` shows the `backend` CI job failing at the
`uv run --no-sync ruff format --check .` step (exit code 1) — `ruff check .` and everything
before it passes; only formatting is out of sync:

```
Would reformat: app/api/auth.py
Would reformat: app/net/ssrf_guard.py
Would reformat: tests/test_auth_service.py
Would reformat: tests/test_llm_redaction.py
Would reformat: tests/test_sso_service.py
5 files would be reformatted, 167 files already formatted
```

Reproduced locally: `cd backend && uv run --no-sync ruff format --check .` fails identically.
These 5 files were touched across the recent SEC-block tasks (SEC-04/SEC-06 auth work,
SEC-01 SSRF guard, SEC-08 redaction tests) without a final `ruff format` pass.

## What to do
1. `cd backend && uv run --no-sync ruff format .` (auto-formats in place — no manual edits) —
   or apply the equivalent via your tooling.
2. Re-run `uv run --no-sync ruff format --check .` and confirm it now reports **0** files to
   reformat.
3. Re-run `uv run --no-sync ruff check .` (should still pass — formatting-only fix, no lint
   changes expected) and the full backend test suite to confirm nothing behavioral changed
   (pure whitespace/formatting).
4. Diff the 5 files to sanity-check the changes are purely formatting (line wrapping/quote
   style/etc.) and not an accidental behavior change from `ruff format`.

## Acceptance criteria
- [ ] `ruff format --check .` passes with 0 files needing reformatting.
- [ ] `ruff check .` still passes.
- [ ] Full backend test suite still green (no behavioral change from the formatting fix).
- [ ] Diff of the 5 touched files is formatting-only.

## Design references
- `dev-board/failed_pipeline.log` — the failing CI run.
- `.github/workflows/backend-ci.yml` — the CI job this fixes.

## Constraints / non-goals
- Formatting-only fix. Do not refactor or change behavior in the 5 files beyond what
  `ruff format` itself applies.
