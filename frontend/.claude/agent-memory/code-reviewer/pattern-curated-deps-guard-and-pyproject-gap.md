---
name: pattern-curated-deps-guard-and-pyproject-gap
description: Backend CI runs a hand-curated `uv pip install` (not full `uv sync`); how to verify a curated-deps allowlist is honest, plus the joserfc/aiosqlite pyproject packaging gap
metadata:
  type: project
---

Backend CI (`.github/workflows/backend-ci.yml`) + `backend/Makefile install` deliberately run a
hand-curated `uv pip install <light-deps>` instead of `uv sync`, to skip the heavy ML stack
(torch/docling). `scripts/check_curated_deps.py` (P8-08) guards drift: diffs pyproject runtime deps
vs both curated lists, respecting an `INTENTIONAL_EXCLUSIONS` allowlist; also enforces CI↔Makefile
list parity and stale-allowlist honesty. Stdlib-only (`tomllib`, needs system python ≥3.11).

**How to review such an allowlist for honesty (the real check):** an entry is legitimate only if the
dep is NOT hit at pytest *collection* — i.e. module-scope-safe. Verify per entry by grepping `app/`:
a **deferred** import (`# noqa: PLC0415 - deferred`, import inside a method) is fine to exclude;
a **module-scope** import is only fine if transitively pulled by a curated extra (e.g. `redis` is
`from redis.asyncio import Redis` at module scope in `app/bootstrap.py` but installed via curated
`celery[redis]`). "Declared but not yet imported" (langmem, google-search-results) is also fine.
The allowlist is externally anchored by CI being green on that exact curated list — it codifies a
known-good state, so don't gate on it if greps confirm each reason.

**Latent packaging gap (project fact, out of P8-08's scope):** `joserfc` and `aiosqlite` are
curated-in (CI + Makefile) but MISSING from `backend/pyproject.toml [project].dependencies`.
`joserfc` is a real always-used runtime dep (`app/security/tokens.py`) — a prod `uv sync` /
`pip install .` would not install it. The drift guard is intentionally one-way (declared-but-not-
curated only), so it will never catch this. **How to apply:** if a task touches packaging/deps or
prod install, flag adding `joserfc` (and reassess `aiosqlite`, a test-only driver) to pyproject.
Relates to [[pattern-verification-module-guard-scans]].
