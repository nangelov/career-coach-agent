---
name: check-cross-cutting-drift
description: Recurring cross-task drift patterns in this backend worth checking on any multi-task/audit review
metadata:
  type: project
---

Cross-cutting quality patterns found in the CR-01 whole-codebase audit (P0-P2) — check these
whenever reviewing work that spans tasks built by separate engineer dispatches.

**Why:** each task is a fresh engineer dispatch, so the same helper/fixture gets re-invented
slightly differently instead of shared. The code is otherwise strong (clean layering, no
driver leaks outside `repositories/` + `llm/client.py`, config fully in `app/config.py`, DI
consistent, no reintroduced global state), so drift is where the real minor findings live.

**How to apply — concrete checks:**
- **`app.state` key literals.** `"pg_provider"`, `"redis_provider"`, `"chat_service"` are
  written/read as bare string literals across `app/main.py`, `app/api/chat.py`, and
  `app/repositories/postgres.py`. They MUST agree for shutdown pool-close + lazy service
  cache to work; a mismatch fails silently (best-effort getattr→None). `_REDIS_PROVIDER_ATTR`
  in chat.py was the intended constant but is unused. If a new task adds an `app.state` key,
  push for a shared constants module rather than more literals.
- **Duplicated test fakes.** `FakeRouter` / `FakeRegistry` (and `_FakeRouter` /
  `_FakeRegistry`) are re-declared near-verbatim in ~5 test modules (test_chat_service,
  test_message_id, test_chat_persistence, test_session_memory, test_p2_exit_verification).
  Some track `executed`, some don't. Flag new copies; a `tests/fakes.py` / conftest fixture
  is the fix. `conftest.py` currently only seeds dummy env secrets (HF_API_TOKEN, DATABASE_URL,
  JWT_SECRET_KEY) — no shared fixtures yet.
- **Best-effort logging convention.** Services log swallowed failures with
  `logger.warning(..., exc_info=True)` (chat.py `_load_prior`/`_persist_turn`); tools
  (`internet_search`) swallow httpx errors into `ToolResult.error` WITHOUT a logger — an
  observability gap, not a correctness bug. Check new tools/adapters log swallowed upstream
  errors. Repositories/tools mostly have no logger (they raise; the service logs) — that's
  the intended split, don't false-positive on it.
- **Don't re-litigate documented deferrals:** mid-stream resume prefix-continuation risk
  (§6.6-locked), conversation get-or-create race (one-in-flight-per-session invariant),
  vector exact-scan vs binary-quantize HNSW prefilter (P2-04 deferred). All flagged already.
