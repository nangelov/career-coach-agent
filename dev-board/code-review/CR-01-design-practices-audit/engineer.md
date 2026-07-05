# Engineer report — CR-01-design-practices-audit · Revision 2

## Summary
This is a **fix pass on a review-only audit**. There was no engineer revision 1 — "revision 1"
was the whole-codebase design-practices audit itself (both `code-review.md` and
`architecture-review.md` returned `APPROVED` with only minor/nit follow-ups). This revision 2
addresses every one of those follow-ups. It is a **pure refactor / cleanup pass**: no behaviour
change, no new features, no schema/migration changes. All finding ids A3–A8 (architecture) and
C1–C5 (code review) are fixed; C6 was explicitly "no action" per the reviewers and is skipped.

Because A3 (composition-root move) and C1/C2 (app.state keys) touch the same files, they were
done together as one coherent change: a new composition-root module `app/bootstrap.py` and a new
shared `app/app_state.py` (`AppStateKeys` StrEnum) referenced everywhere the three `app.state`
attributes are read/written.

## Files changed
- `app/app_state.py` — **new.** `AppStateKeys(StrEnum)` — the single contract for the three
  `app.state` attribute names (`pg_provider`, `redis_provider`, `chat_service`). Low-level module
  with no app imports, so every consumer (main, bootstrap, api/chat, repositories/postgres) can
  reference it without a circular dependency. (C1, C2)
- `app/bootstrap.py` — **new.** Composition root: `build_chat_service(app)` moved here out of the
  API layer. Assembles the shared Redis provider + LLM router + tool registry + session memory +
  cancel registry + durable conversation store. (A3)
- `app/api/chat.py` — now **thin**: dropped `build_chat_service` and all 6 repository/LLM imports;
  keeps only the `get_chat_service` dependency (delegating to `app.bootstrap`) + SSE plumbing.
  Removed the dead `_REDIS_PROVIDER_ATTR` constant and the `_SERVICE_ATTR` literal (→ `AppStateKeys`).
  Refreshed the stale "P2 moves the rest of the composition" docstring. (A3, C1, C2)
- `app/main.py` — lifespan uses `AppStateKeys` for the pg-provider write and all shutdown reads;
  extracted `_best_effort_aclose(obj, label)` and call it thrice (service → pg → redis), replacing
  three copy/pasted try/except blocks; updated the stale "P2 will move this" comments. (A3, C1, C5)
- `app/repositories/postgres.py` — `get_db_session` reads `AppStateKeys.PG_PROVIDER` instead of the
  `"pg_provider"` literal. (C1)
- `app/repositories/models/_mixins.py` — **new.** Shared `CreatedAtMixin` (extracted from the 4
  verbatim copies). (A4)
- `app/repositories/models/{identity,knowledge,dashboard,jobs}.py` — deleted the local
  `_CreatedAtMixin`; import and subclass the shared `CreatedAtMixin`. (A4)
- `app/repositories/conversation_store.py` — `PostgresConversationStore` gains a keyword-only
  `history_limit` constructor param + a `from_settings(provider, config=settings)` classmethod
  matching its siblings; `load_history` uses `self._history_limit` instead of the query-time global
  `settings.SESSION_MEMORY_MAX_MESSAGES`. (A5)
- `app/services/chat.py` — `ChatService.__init__` now emits a `logger.warning` when it falls back to
  the in-memory `SessionMemory`/`CancelRegistry` doubles (the v1 global-state anti-pattern signal). (A6)
- `app/llm/types.py` — `ToolSchema = dict[str, Any]` now defined here (the SDK-free vocabulary
  module). (A8)
- `app/llm/client.py` — imports/re-exports `ToolSchema` from `types` (via `__all__`) instead of
  redefining it. (A8)
- `app/tools/base.py` — imports/re-exports `ToolSchema` from `app.llm.types` (via `__all__`) instead
  of redefining it; existing `from .base import ToolSchema` sites keep working. (A8)
- `app/tools/internet_search.py` — added a module `logger` and `logger.warning(..., exc_info=True)`
  before the swallowed `TimeoutException`/`HTTPError` → `ToolResult.error(...)` returns. (C4)
- `tests/fakes.py` — **new.** Shared `FakeRouter` / `FakeRegistry` / `Script` — one home for the
  scripted-router / canned-registry contract. (C3)
- `tests/test_chat_service.py`, `tests/test_message_id.py`, `tests/test_chat_persistence.py`,
  `tests/test_session_memory.py`, `tests/test_p2_exit_verification.py` — deleted their local
  `FakeRouter`/`FakeRegistry`/`_FakeRouter`/`_FakeRegistry` copies and import from `tests.fakes`;
  pruned now-unused imports. (C3)
- `tests/test_embeddings.py` — added `test_embedding_dimension_matches_orm_vector_width`
  asserting `EmbeddingClient.DIMENSION == EMBEDDING_DIM` (a test, not a cross-layer import, so the
  models→llm dependency direction stays correct). (A7)

## Key decisions
- **`AppStateKeys` in its own low-level module (`app/app_state.py`), not in `bootstrap.py`.** The
  repository layer (`repositories/postgres.py`) must reference the pg-provider key, and a repository
  importing the composition root would invert the dependency direction. A tiny, dependency-free
  module keeps the direction correct and lets everyone import the same enum. (C1)
- **A3 stays lazy, only relocated.** `build_chat_service` moved from the API layer into a dedicated
  composition-root module (`app/bootstrap.py`) but is still invoked lazily on first request (via
  `get_chat_service`), preserving the exact startup/failure behaviour — this is a pure refactor, so
  no eager-at-boot Redis connection was introduced. The architecture concern A3 flagged (composition
  misplaced in the API layer, API importing 6 repo types) is fully resolved; the eager-vs-lazy
  asymmetry it noted as a *consequence* is left as-is to honour the "no behaviour change" constraint.
- **A5 uses a keyword-only `history_limit` with a `100` default + `from_settings`** — mirroring the
  sibling `RedisSessionMemory(..., max_messages: int = 100)` pattern exactly. The composition root
  builds it via `from_settings` (injecting `SESSION_MEMORY_MAX_MESSAGES`); the `100` default equals
  the config default, so the 6 existing direct-construction test sites keep working unchanged and
  behaviour is identical to the old query-time read.
- **A6 chose the `logger.warning` fallback signal, not required params** — this was the explicit
  "less disruptive" tiebreaker: `cancel` (and sometimes `memory`) is legitimately omitted by ~5 unit
  test call sites where the in-memory double is the correct test default, so making them required
  would churn many tests. The warning gives the production mis-wire signal A6 asked for with zero
  call-site changes. Production wiring (`app.bootstrap`) always injects both, so the warning never
  fires there.
- **A8 was a clean, low-risk move, so it was done.** `ToolSchema` now lives once in the SDK-free
  `llm/types.py` and is re-exported from both `llm/client.py` and `tools/base.py` via `__all__`, so
  no import site changed and `tools/` still never pulls in the `openai` SDK.

## How to verify
From `backend/` (using the project venv):
- `.venv/bin/ruff check app tests` → All checks passed
- `.venv/bin/ruff format --check app tests` → 65 files already formatted
- `.venv/bin/mypy app/` → Success: no issues found in 44 source files
- `.venv/bin/pytest -q` → **102 passed, 40 skipped** (was 101/40; +1 is the new A7 equality test;
  the 40 skips are the live-Postgres integration suites that skip without a DB, unchanged)

## Self-check
- [x] Meets acceptance criteria — every listed finding (A3–A8, C1–C5) addressed; C6 correctly skipped
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (the API layer is now
      strictly thinner — zero repository imports; composition is in the dedicated `app/bootstrap.py`)
- [x] Pure refactor: no behaviour change, no new features, no schema/migration changes
- [x] Tests/lints pass (results pasted above)

## Response to review
- **A3 (composition root split/misplaced)** → Fixed. Moved `build_chat_service` out of `api/chat.py`
  into a new composition-root module `app/bootstrap.py`; `api/chat.py` now holds only the
  `get_chat_service` dependency + SSE plumbing and imports no repository/LLM types. Updated the stale
  "P2 will move this" comments in both `api/chat.py` and `main.py`. Kept the wiring lazy (relocated,
  not made eager) to preserve behaviour per the no-behaviour-change constraint.
- **A4 (`_CreatedAtMixin` duplicated 4×)** → Fixed. Extracted to `app/repositories/models/_mixins.py`
  as `CreatedAtMixin`; all four model modules import and subclass it.
- **A5 (`load_history` reads global at query time)** → Fixed. Added keyword-only `history_limit`
  constructor param + `from_settings` classmethod matching siblings; `load_history` uses the injected
  value; composition root builds via `from_settings`.
- **A6 (silent in-memory fallback)** → Fixed via the `logger.warning` option (chosen as least
  disruptive — documented above under Key decisions). A production composition that dropped the
  `memory`/`cancel` arg now logs a clear warning instead of silently reintroducing per-process state.
- **A7 (two unlinked 4096 constants)** → Fixed. Added `test_embedding_dimension_matches_orm_vector_width`
  asserting `EmbeddingClient.DIMENSION == EMBEDDING_DIM`; kept as a test (no cross-layer import) so
  models do not import `llm/`.
- **A8 (`ToolSchema` defined twice)** → Fixed (clean, low-risk). Moved the alias to the SDK-free
  `llm/types.py`; re-exported from `llm/client.py` and `tools/base.py` via `__all__`. No import site
  changed; `tools/` still does not import the `openai` SDK.
- **C1 (three `app.state` keys as bare literals)** → Fixed. New `AppStateKeys(StrEnum)` in
  `app/app_state.py`; referenced at every read/write site in `main.py`, `bootstrap.py`, `api/chat.py`,
  and `repositories/postgres.py`.
- **C2 (dead `_REDIS_PROVIDER_ATTR`)** → Fixed. Deleted; folded into `AppStateKeys.REDIS_PROVIDER`
  (used at the bootstrap write site and the `main.py` shutdown read).
- **C3 (fakes re-declared across 5 test modules)** → Fixed. Extracted shared `FakeRouter`/
  `FakeRegistry`/`Script` into `tests/fakes.py`; all five modules import them (kept only their
  test-specific specialised fakes like `_CancelMidStream`, `FakeConversationStore`).
- **C4 (internet_search swallows errors without logging)** → Fixed. Added a module `logger` and
  `logger.warning(..., exc_info=True)` before both graceful `ToolResult.error` returns.
- **C5 (shutdown try/except repeated 3×)** → Fixed. Extracted `_best_effort_aclose(obj, label)` in
  `main.py`; called thrice.
- **C6 (`get_message` linear scan)** → No action, as the reviewers instructed (deferred to P9).
