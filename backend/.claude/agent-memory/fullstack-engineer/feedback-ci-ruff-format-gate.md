---
name: feedback-ci-ruff-format-gate
description: Backend CI gate includes `ruff format --check .` (not just `ruff check`); a pinned-ruff version bump silently makes older-formatted committed files fail it
metadata:
  type: feedback
---

The backend CI (`.github/workflows/backend-ci.yml`) and `make check` run **four** gates:
`ruff check .`, **`ruff format --check .`**, `mypy app/ migrations/`, and `pytest`. It is
easy to forget the `ruff format --check` step and hand off with red CI even though
`ruff check` passes.

**Why it bites:** `uv.lock` pins an exact ruff (e.g. 0.15.20). When the lock's ruff is
bumped, its formatter may collapse/rewrap lines differently, so files formatted by an older
ruff and committed clean now **fail `ruff format --check`** — a pre-existing drift unrelated
to your task that nonetheless reds the gate for everyone.

**How to apply:** always run `uv run --no-sync ruff format --check .` (or `make check`) as
part of the final gate, not just `ruff check`. If it flags files you did not touch, it is
mechanical version drift — fix with `uv run --no-sync ruff format <files>` (zero logic
change) and call it out explicitly in the report as out-of-scope pre-existing cleanup, since
a verification/handoff task must leave the whole CI gate green.
