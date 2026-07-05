# Architecture review — CR-01-design-practices-audit · engineer revision n/a (review-only audit)

Scope reviewed: everything shipped in P0+P1+P2 — `backend/app/` (api, services, repositories,
repositories/models, llm, tools, tasks, schemas, config, main), `backend/migrations/`,
`backend/tests/`. **Frontend is out of scope for this pass**: P2 was backend-only; the frontend
(P0-05/P0-13/P1-08) was reviewed and approved in its own tasks and has not changed since.
This file covers design-conformance concerns; correctness/security/quality is the parallel
`code-review.md`.

## Verdict: APPROVED

No blocker/major design deviations. The codebase conforms to §8 structure, the
Router→Service→Agent/Repository layering, the ports-and-adapters seams, and every locked v2
decision. Six minor/nit findings are logged below as required follow-ups (A3–A8) — all cheap
to fix now, and A3/A4 get more expensive with each later phase, so they should be scheduled
before/at P3 and P8 respectively.

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | Code in the right modules: `api/`, `services/`, `repositories/` (+`models/` groups), `llm/`, `tools/`, `tasks/`, `schemas/`, `migrations/`, `tests/`; placeholders for P3+ (`agents/`, `guardrails/`, `ingestion/`, `memory/`, `pdf/`) | Exactly as designed. ORM models grouped sanely by table group (`models/identity.py`, `knowledge.py`, `dashboard.py`, `jobs.py`, aggregated in `models/__init__.py` for `Base.metadata`); `postgres.py` stays the clean engine/pool foundation (no query logic leaked in — conversation persistence correctly lives in its own adapter `repositories/conversation_store.py`); placeholder packages empty as they should be | None |
| A2 | Layering (§8, tasks.md DoD: "no driver access in services") | Router → Service → Repository; services never import DB drivers | Verified by grep: `app/services/` has **zero** `sqlalchemy`/`redis`/driver imports — services depend only on the ports (`SessionMemory`, `CancelRegistry`, `ConversationStore`). `api/chat.py` at request time only calls `service.stream_turn`/`request_cancel`; its repository imports serve composition only (see A3). Repositories own all driver access; `vector_search.py` takes `AsyncSession` + injects `EmbeddingClient` (TYPE_CHECKING import only) | None at request time; composition-root placement → A3 |
| A3 | Composition root / SoC (§4 shared pools, §8) | One composition root (app lifespan) builds the shared pools and services; API modules stay thin | **Split + misplaced composition root**: `app/api/chat.py:59-93` (`build_chat_service`) lazily builds the Redis pool provider, `LLMRouter`, tool registry, session memory, cancel registry, and `PostgresConversationStore` on first request and stashes providers on `app.state` from inside the API layer, while `app/main.py:76-78` builds the Postgres pool eagerly in the lifespan. Consequences: asymmetric failure posture (Postgres fails fast at boot, Redis fails late on first user request), the lifespan shutdown defensively reaches into three separate `app.state` attributes it didn't all create (`main.py:92-113`), and the API module imports 6 repository/llm types. The code's own comments (`api/chat.py:20-22, 67-68`; `main.py:84-85`) promised "P2 moves the remaining composition to shared pools" — P2 is complete and it did not move | **Minor — required follow-up before/at P3 start.** Move `build_chat_service` composition into the lifespan (or a dedicated `app/bootstrap.py`), keep only the `get_chat_service` dependency in `api/chat.py`, and update the stale "P2 will move this" comments. P3 (auth needs the same Redis pool for sessions/rate-limits) and P4 (agents need the router) will each otherwise grow their own lazy wiring path |
| A4 | DRY — ORM model modules (§4/§8) | Shared model plumbing defined once | `_CreatedAtMixin` is duplicated **verbatim 4×**: `models/identity.py:60-67`, `models/knowledge.py:92-99`, `models/dashboard.py:79-86`, `models/jobs.py:53-60`. Identical 8 lines; a future change (e.g. timestamp precision/timezone behavior) can now half-land | **Minor.** Extract to one shared module (e.g. `app/repositories/models/_mixins.py`) and import it in all four; do this before P8 confirms/extends dashboard tables and a 5th copy appears |
| A5 | Consistency — config injection (task.md "consistency across dispatches") | Adapters take config at construction via the established `from_settings(...)` pattern (`RedisSessionMemory`, `RedisCancelRegistry`, `LLMRouter`, `HFOpenAICompatibleClient`, `InternetSearchTool` all do) | `PostgresConversationStore` alone reads the **global** `settings.SESSION_MEMORY_MAX_MESSAGES` at query time inside `load_history` (`repositories/conversation_store.py:30, 157`) instead of constructor injection — the only adapter that couples to the module-level singleton in a method body (weaker testability, drift from the blessed pattern) | **Minor.** Add a `history_limit: int` constructor param (populated from settings at the composition root, e.g. via a `from_settings` classmethod matching its siblings) |
| A6 | Testability / no hidden global state (task.md; the v1 `ConversationBufferMemory` lesson) | Production wiring is explicit; process-local stores are test doubles only (`session_memory.py` and `cancellation.py` docstrings say exactly this) | `ChatService.__init__` **silently defaults** to `InMemorySessionMemory()` / `InMemoryCancelRegistry()` when the args are omitted (`services/chat.py:150-151`). A mis-wired composition (e.g. a future refactor of A3 dropping an argument) would silently reintroduce per-process conversation state — the exact v1 failure mode v2 exists to remove — with no error or log | **Minor.** Make `memory`/`cancel` required parameters (tests already can pass fakes explicitly), or at minimum emit a `logger.warning` when the in-memory fallback is taken |
| A7 | DRY — the locked 4096 dimension (§6 item 3) | One authoritative dimension constant | Two independent, unlinked `4096` constants: `EmbeddingClient.DIMENSION` (`llm/embeddings.py:79`) and `EMBEDDING_DIM` (`models/knowledge.py:82`). Tests assert each equals 4096 separately but nothing asserts they equal **each other**; a future coordinated dim migration could half-land | **Nit.** Add a one-line test `EmbeddingClient.DIMENSION == EMBEDDING_DIM` (a test is preferable to a cross-layer import — models importing `llm/` would invert the dependency direction) |
| A8 | DRY — `ToolSchema` alias | Single home for shared vocabulary | `ToolSchema = dict[str, Any]` defined twice (`llm/client.py:65`, `tools/base.py:39`). Deliberate and documented (importing it from `client.py` would pull the `openai` SDK into `tools/`) — but `llm/types.py` is SDK-free and already the shared vocabulary module | **Nit / optional.** Move the alias to `llm/types.py` and re-export from both current locations |
| A9 | Locked decisions (§6, plan.md "Decisions locked before P1") | All 9 honored | All verified — see checklist below. Notably: no ReAct/text-parsing anywhere (grep clean; `output_parser.py` exists only under `legacy-code/`); users table has **no password column** (§7.1); embeddings in-process, `vector(4096)` consistent across `EmbeddingClient`, ORM, and migration 0003 (incl. the documented binary-quantize HNSW workaround for the >2000-dim index cap); mid-stream **resume** implemented solely in `llm/router.py` with the single client at `max_retries=0` (the blessed P1-01/02 split); guests (`user_id=None`) never touch Postgres | None |
| A10 | Phase fit (plan.md P0–P2 scope; task.md "don't flag P3+ as missing") | Nothing premature; interim seams documented | Clean. The client-supplied `ChatRequest.user_id` is the blessed P2-07 interim seam, explicitly documented as **not an authorization boundary** with P3 replacing it from the verified JWT (`schemas/chat.py:54-64`); cancel-endpoint auth gap likewise documented as P3 (`api/chat.py:162-165`). No LangGraph/auth/guardrails built early | None — but P3 **must** remove the client-trusted `user_id` field as documented; flagging here so it is not forgotten |
| A11 | Config/secrets hygiene (§7, tasks.md DoD) | All config via `app/config.py` pydantic-settings; no hardcoded values/secrets | Every knob (timeouts, TTLs, caps, pool sizes, model ids, backoff, circuit thresholds) is a `Settings` field with description; required secrets fail fast; Celery broker from `settings.REDIS_URL`; alembic `env.py` injects `DATABASE_URL` from the same `Settings` (no duplicated DSN); `tests/conftest.py` seeds clearly-dummy placeholders only | None |
| A12 | Error handling & resilience posture | Consistent best-effort-vs-fail-hard split | Consistent: startup fails hard on Postgres unreachable (`verify_connectivity`); durable persistence and rehydration are best-effort (logged, swallowed, after the terminal SSE event — blessed P2-07 pattern); tools never crash the model loop (`ToolRegistry.execute` converts every failure to a graceful tool message); the service never leaks a mid-stream 500. Terminal-error paths deliberately skip persistence with a written rationale (`services/chat.py:306-307`) | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — verified module-by-module and by grep (no driver imports in `services/`)
- [x] Honors locked decisions — no ReAct parser (native `tool_calls` end-to-end); Postgres+Redis only (no Mongo anywhere); SSO-only schema (no password/credential column, minimal-PII `users`); in-process `sentence-transformers` embeddings at 4096 consistent with `vector(4096)` migrations; LangGraph correctly deferred to P4 (P1 walking skeleton documented as interim); Celery on Redis broker; failover router with mid-stream resume + Redis circuit-breaker; guest turns Redis-only
- [x] Interfaces-before-implementations — `LLMClient` (ABC, SDK confined to `client.py`), `EmbeddingClient` (ABC, lazy-load + injectable encoder), `SessionMemory` / `CancelRegistry` / `ConversationStore` (ports in `services/`, adapters in `repositories/`), `Tool`/`ToolRegistry`, structural `RedisLike`/`SessionRedis`/`CancelRedis` Protocols keeping driver types out of consumer signatures. `DocumentParser`/guardrails not yet due (P5/P10)
- [x] Budget posture respected (§11) — SearXNG (OSS, keyless, self-hostable) for search; no paid last-resort in the model list; self-hosted Postgres/Redis; in-process embeddings (no API cost); pool caps (5 Postgres / 10 Redis) per §4

## Notes
- **SOLID summary:** SRP is strong (each module one concern; `ChatService` at 449 lines is the
  documented P1 interim single-agent loop that P4's LangGraph replaces — acceptable). OCP/DIP are
  the codebase's best trait: every external dependency sits behind an ABC or Protocol with the
  concrete adapter at the edge. LSP holds (in-memory and Redis/Postgres adapters are
  behaviorally interchangeable behind their ports; tests exercise both). ISP holds via the
  minimal per-consumer Redis Protocols rather than one fat interface.
- **Consistency across dispatches** (each task built by a fresh engineer) is remarkably good:
  the `from_settings` classmethod, ports-in-`services/`/adapters-in-`repositories/`, checked-varchar-
  not-ENUM, `_ROLE_VALUES`-style vocab tuples, GDPR cascade postures, and logging patterns all
  carried across P1→P2. A5 is the one drift instance found.
- **Follow-up schedule:** A3 before/at P3 kickoff (auth will need the shared pools); A4 before
  P8 (next table group); A5–A8 opportunistic (fold into the A3 fix pass or the next backend task).
- Naming-collision handling is deliberate and good: `DashboardTask` vs Celery `tasks/`,
  `meta` attr → `"metadata"` column, ORM `Session` vs SQLAlchemy `AsyncSession` kept distinct.
- Migrations: `env.py` correctly single-sources `DATABASE_URL` from `Settings` and targets the
  one `Base.metadata`; the hand-managed functional HNSW indexes are excluded from autogenerate
  with rationale — drift checks stay clean. Frozen `EMBEDDING_DIM = 4096` copies inside
  migration files are correct practice (migrations are snapshots, not consumers of live code).

## Verdict: APPROVED

---

# Architecture re-review — CR-01-design-practices-audit · engineer revision 2 (fix pass)

Scope: verify the revision-2 fixes for A3–A8 are genuinely implemented (not just claimed), that
the composition-root move introduced no new layering/design violations, and that all locked v2
decisions still hold. Every fix was verified by reading the code, plus grep for driver imports in
`services/`/`api/` and a full local run (`ruff` clean, `mypy` clean on 44 files,
`pytest -q` → **102 passed, 40 skipped** — matching the engineer's report; the +1 is the new A7 test).

## Fix verification

| id | rev-1 finding | rev-2 status | verified observation |
|----|---------------|--------------|----------------------|
| A3 | Composition root split/misplaced (built in `api/chat.py`, pools asymmetric, stale "P2 will move this" comments) | **Fixed** | `build_chat_service` now lives in the dedicated composition-root module `app/bootstrap.py` — exactly one of the two remedies A3 offered ("lifespan **or** a dedicated bootstrap module"). `api/chat.py` is genuinely thin: zero repository/LLM imports (grep-verified), only `get_chat_service` (delegating to `app.bootstrap`) + SSE plumbing + the cancel route. Stale comments replaced with accurate docstrings in both `api/chat.py` and `main.py`. `bootstrap.py`'s docstring explicitly anticipates P3 (auth Redis) and P4 (agents router) extending this one wiring path — the exact future-coupling A3 was guarding against |
| A4 | `_CreatedAtMixin` duplicated verbatim 4× | **Fixed** | Extracted to `app/repositories/models/_mixins.py` as `CreatedAtMixin`; grep confirms all four modules (`identity`, `knowledge`, `dashboard`, `jobs`) import and subclass it and **no local copy remains** anywhere |
| A5 | `PostgresConversationStore.load_history` read global `settings` at query time | **Fixed** | Keyword-only `history_limit` constructor param (guarded `max(1, …)`, default `100` mirroring the sibling `RedisSessionMemory` pattern and the config default) + a `from_settings(provider, config)` classmethod matching every sibling adapter; `load_history` uses `self._history_limit`; the composition root builds via `from_settings`. The rev-1 consistency drift is gone |
| A6 | `ChatService.__init__` silently defaulted to in-memory stores | **Fixed (warning option)** | `logger.warning` fires listing exactly which fallback(s) were taken, naming `app.bootstrap.build_chat_service` as the correct production wiring. A6 explicitly offered "required params **or** a warning"; the engineer chose the warning with a documented rationale (≈5 legitimate unit-test call sites). Acceptable — the production mis-wire is no longer silent, which was the design point (the v1 global-state failure mode now announces itself) |
| A7 | Two unlinked `4096` constants | **Fixed** | `tests/test_embeddings.py::test_embedding_dimension_matches_orm_vector_width` asserts `EmbeddingClient.DIMENSION == EMBEDDING_DIM` — done as a test, not a cross-layer import, exactly as A7 required (models still do not import `llm/`) |
| A8 | `ToolSchema` alias defined twice | **Fixed** | Single definition in the SDK-free `app/llm/types.py`; `llm/client.py` and `tools/base.py` import and re-export via `__all__` (grep confirms no second definition); `tools/` still pulls in no `openai` SDK |

## New-code design check (no regressions introduced)

- **`app/bootstrap.py`** — correct composition-root posture: it is the *only* module allowed to
  import across all layers (repositories + services + tools + llm + config), and nothing imports
  it except the thin `get_chat_service` dependency. Dependency direction is clean:
  `api → bootstrap → services/repositories`; no repository or service imports `bootstrap`. The
  single-shared-Redis-client rule (§4) and the composition-boundary `cast`s carried over intact.
- **`app/app_state.py`** — a dependency-free leaf constants module (`AppStateKeys` StrEnum), so
  `repositories/postgres.py` referencing it does **not** invert any layer (it would have been a
  violation to put these keys in `bootstrap.py`; the engineer's key decision got this right).
  All five read/write sites (`main`, `bootstrap`, `api/chat`, `repositories/postgres`) now share
  one contract — the C1/C2 silent-drift trap is closed.
- **`main.py`** — lifespan still fails fast on Postgres (`verify_connectivity`), shutdown closes
  service → Postgres → Redis via the extracted `_best_effort_aclose` (C5), reading only
  `AppStateKeys` members with `getattr(…, None)` so a never-built resource is a no-op. No
  behaviour change, as claimed.
- **Eager-Postgres vs lazy-Redis asymmetry** — unchanged, *by explicit documented decision*
  (rev-1 A3 listed it as a consequence, not the required change; the required change was the
  relocation, which is done). The lazy-Redis rationale is now written down in `bootstrap.py`'s
  docstring. This stays acceptable **until P3**, where auth/rate-limiting makes Redis a hard
  startup dependency anyway — at that point the lifespan should invoke `build_chat_service` (or
  at least the Redis provider) eagerly so both pools share the fail-fast posture. Logged as a
  P3 note, not a finding.
- **Locked v2 decisions** — untouched by this refactor and re-verified: no ReAct parsing, no
  Mongo, no password paths, in-process embeddings at 4096 (now with the A7 cross-check test),
  failover/resume confined to `llm/router.py`, guests Redis-only, budget posture unchanged.
  Rev-1 rows A1–A2 and A9–A12 stand.

## Cross-cutting checks (revision 2)
- [x] Fits target structure (§8) + layering — API layer strictly thinner than rev 1; composition in one root; grep-clean `services/` and `api/` (no driver imports)
- [x] Honors locked decisions — unchanged, re-verified
- [x] Interfaces-before-implementations — all ports/adapters intact; `from_settings` pattern now uniform across every adapter (A5 closed the one drift)
- [x] Budget posture respected — unchanged

## Notes
- Carry-forward to P3 (unchanged from rev 1 where still open): (1) remove the client-trusted
  `ChatRequest.user_id` interim seam (A10); (2) consider warming the Redis pool /
  `build_chat_service` in the lifespan once P3 makes Redis a hard dependency, unifying the
  fail-fast posture. A3–A8 themselves are **closed**.
- C6 (linear `get_message` scan) was correctly left alone per the reviewers' explicit deferral to P9.

## Verdict: APPROVED
