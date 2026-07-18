# Engineer report — P8-08-curated-deps-guard · Revision 1

## Summary
Added an automated, stdlib-only guard that fails fast (naming the exact package) when a
runtime dependency declared in `backend/pyproject.toml` is missing from the curated CI/Makefile
`uv pip install` list — the FIX-01/02/03/04/09/11 recurring bug class. The guard also enforces
that the two curated lists (backend-ci.yml and backend/Makefile) stay identical to each other,
and keeps its own intentional-exclusion allowlist honest. Wired as an early CI step (before the
slow install/pytest steps) and as a `make check-deps` target (first step of `make check`).

## Files changed
- `backend/scripts/check_curated_deps.py` — new guard. Parses `[project].dependencies` +
  `[dependency-groups].dev` via stdlib `tomllib`, extracts the curated `uv pip install` package
  names from both `.github/workflows/backend-ci.yml` and `backend/Makefile` (joining backslash
  continuations, skipping comment lines), and reports drift. No third-party imports, so it runs
  before any dependency is installed.
- `backend/tests/test_curated_deps.py` — new tests: positive (real repo files are clean),
  parsing helpers (normalize/YAML/Makefile), and negative cases (uncurated dep, allowlisted dep,
  dev-group dep, CI↔Makefile drift, stale allowlist entry).
- `.github/workflows/backend-ci.yml` — added "Curated-dependency drift guard" step
  (`python3 scripts/check_curated_deps.py`) right after Python setup, before install/pytest, with
  an explanatory comment.
- `backend/Makefile` — added `check-deps` target (documented) and prepended it to `check`;
  added to `.PHONY`.

## Key decisions
- **Static diff, not import-walking** (task Design §1): parse `pyproject.toml` deps and diff
  against the curated lists, respecting a documented allowlist. Avoids false positives on
  stdlib/dev-only/lazy imports.
- **Intentional-exclusion allowlist is explicit + reasoned** in the script. It is broader than
  pure ML because that matches what is actually excluded from the curated venv today: `uvicorn`
  (server, never imported in tests), `redis` (imported at module scope but installed transitively
  via the curated `celery[redis]` extra — verified `app/bootstrap.py`), `sentence-transformers`,
  `docling`, `pillow`, `pytesseract`, `ocrmypdf` (lazy/ML), `langmem` (declared, not yet
  imported), `google-search-results` (not yet imported). `httpx` needs no allowlist entry — it is
  in the dev group and installed via `uv sync --only-group dev`, which the guard treats as covered.
- **Enforce CI↔Makefile parity** (Design §2): the workflow comment already says "keep in sync";
  now the guard fails if the two lists differ, catching the same bug class in miniature.
- **Stdlib-only + `python3`** so it can be the *first* CI step before the venv exists (Design §3).
  The `make check-deps` target uses `python3` for the same reason (no `--no-sync` venv needed).
- **Direction is one-way**: flags declared-but-not-curated, never curated-but-undeclared (e.g.
  `aiosqlite`, `joserfc` are test/curated-only extras and are correctly ignored) — the recurring
  bug is always the former.
- **Allowlist honesty check**: a stale allowlist entry (allowlisted but no longer declared) also
  fails, so the guard cannot silently rot.

## How to verify
- `cd backend && make check-deps` → "guard OK".
- Negative case is covered by unit tests; also demonstrable by temporarily adding a fake dep to
  `pyproject.toml` and re-running — fails naming the package.
- Full gate: `cd backend && uv run --no-sync ruff check . && uv run --no-sync ruff format --check
  . && uv run --no-sync mypy app/ migrations/ && uv run --no-sync pytest`.

## Tests (final step — mandatory)
- `ruff check .` → All checks passed.
- `ruff format --check` (new files) → already formatted.
- `mypy app/ migrations/` → Success, no issues in 139 files (script also mypy-clean).
- `pytest tests/test_curated_deps.py -q` → 9 passed.
- `pytest -q` (full backend) → **739 passed, 62 skipped** (live-DB `*_postgres` tests skip
  offline, as designed).
- Two initial failures were in the *new test* (synthetic allowlist `{torch}` tripped the
  stale-allowlist check because those cases omitted `torch` from `runtime`) — fixed the tests by
  adding `torch` to their runtime sets; the guard logic was correct. Two `E501` long lines in the
  script were shortened. All green after.
- Frontend untouched → frontend CI unaffected.

## Self-check
- [x] Meets acceptance criteria (guard exists, names the package, positive+negative tested, wired
      early in backend-ci.yml, documented in script + CI comment, CI stays green).
- [x] No secrets; no layering impact (CI/tooling-only, no Router/Service/Repo changes).
- [x] Tests/lints pass (results above).
- [x] Non-goal respected: does not switch CI to full `uv sync`; guards the existing curated design.
