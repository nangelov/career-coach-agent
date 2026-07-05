---
name: check-backend-diff-vs-report
description: On backend tasks, reconcile engineer.md "Files changed" against actual git diff — watch for uv.lock churn and zero-diff "restores"
metadata:
  type: project
---

On every backend/ review, run `git diff HEAD --stat` and `git status --short` and reconcile against
engineer.md's "Files changed" list. Two recurring gaps seen here:

- **Unmentioned `backend/uv.lock` churn.** Any target that runs `uv sync`/`uv lock` (e.g. a new `make
  install`) re-resolves and rewrites uv.lock — often `requires-dist` specifier bumps (a stale lock catching
  up to `pyproject.toml`) plus CUDA/nvidia platform-marker re-writes. Usually harmless (no source/behavior
  change), but it's undocumented scope. Verify it's only a re-sync (compare the lock's `requires-dist` line
  against `pyproject.toml` — if they now match, the lock was just stale) → minor/nit, not a gate.
- **Zero-diff "restores."** An engineer may claim to have "restored"/"fixed formatting" in a file (e.g.
  conftest.py). If `git diff HEAD -- <file>` is empty, the file matches the committed baseline = genuinely no
  net change, no behavior change. That satisfies a "is this really just formatting?" concern definitively.

Also: engineer.md narratives sometimes imply pre-existing structure that didn't exist (e.g. "the Makefile
`install` target carried drift" when `install` was newly created). Check with `git show HEAD:<file>` before
believing the framing; usually a nit if the actual change is sound.

Related: [[check-alembic-migration-tasks]], [[check-cross-cutting-drift]].
