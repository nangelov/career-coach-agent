# Engineer report — P8-03-dashboard-tools · Revision 2

## Summary
Wired the P8-02 `DashboardService` into the multi-agent chat graph as a new request-path
`DASHBOARD` worker. The assistant can now, mid-conversation, **read** the user's living PDP and
**propose** goals/milestones/tasks/progress via native tools — every AI write goes through the
service with `source="ai"` (→ `status="proposed"`, pending approval), never silent. Guests fail
soft ("sign in to use the dashboard") without ever building a write-capable tool or calling the
model. Follows the existing `make_market_node` / `make_rag_node` worker shape (factory + closure,
`build_graph` DI kwarg, dependency-free import-time default).

## Files changed
- `app/agents/state.py` — added `Intent.DASHBOARD` and `WorkerName.DASHBOARD` enum members.
- `app/agents/planner.py` — added `dashboard` to the prompt intent list, `_INTENT_WORKERS`
  (→ `[WorkerName.DASHBOARD]`), and `_INTENT_MAX_ITERATIONS` (3). The tool-schema `enum` is
  derived from `_INTENT_VALUES`, so `dashboard` is auto-included.
- `app/tools/dashboard.py` (new) — 5 native `Tool`s over `DashboardService`: `read_dashboard`
  (reuses `get_summary`), `propose_goal`/`propose_milestone`/`propose_task`, `log_progress`.
  Each closes over the caller's `user_id` (built per-turn via `build_dashboard_tools`); every
  propose tool calls the service with `source="ai"` only — no tool passes `status`. OpenAI-shaped
  JSON schemas; graceful `ToolResult.error` on bad args / missing goal (never raises).
- `app/agents/dashboard_agent.py` (new) — `make_dashboard_node(service, router, max_iterations=3)`:
  guest fail-soft, unconfigured fail-soft, else a **bounded** (≤3 rounds) tool-calling loop against
  the injected `LLMCompleter` with `tool_choice="auto"`, producing a `WorkerResult` summarizing what
  was read/proposed (frames AI writes as pending approval). Fails soft on `LLMError`.
- `app/agents/graph.py` — imported/added the module-default `dashboard_node`, a
  `dashboard_service=` kwarg on `build_graph` (+ threaded through `GraphTurnStreamer` and
  `stream_graph`), registered the node. `WORKER_NODES`/fan-in edges derive from `WorkerName`, so
  the node auto-joins the fan-in.
- `app/bootstrap.py` — `build_chat_service` now reuses `build_dashboard_service(app)` (guarded on
  the shared Postgres pool, mirroring `conversations`) and injects it into `GraphTurnStreamer`.
  (Also trimmed two pre-existing 101-char docstring lines in `build_dashboard_service` so the file
  passes the ruff line-length gate.)
- `tests/test_dashboard_tools.py` (new), `tests/test_dashboard_agent.py` (new) — see Tests.
- `tests/test_agent_graph.py` — updated the fan-in test to dispatch `WorkerName.DASHBOARD` too
  (a new enum member): it asserted the dispatched set equals **all** `WorkerName` members, so it
  went stale when the enum grew. The dashboard worker produces no citation, so the citation
  assertions now compare against `set(WorkerName) - {DASHBOARD}`.

## Key decisions
- **Tools bound per-turn, not registered globally** (task §3 / §"constructed per turn"): `Tool.run`
  takes only parsed args, so `user_id` is closed over — the model can never spoof whose dashboard is
  touched. The node builds a fresh `ToolRegistry` per turn.
- **Attribution stays in the service** (design §5.2, task §refs): tools pass `source="ai"` and never
  a `status`; the P8-02 `DashboardService._resolve_status` remains the single place `ai → proposed`
  is decided. No re-implementation in the tool layer.
- **Guest exclusion is enforced in the node, before any tool exists** (§5.2): `state.user_id is None`
  short-circuits to a fail-soft `WorkerResult.error` — defence in depth (a guest never reaches a
  write path).
- **Bounded loop against the shared router** (task §4): the same `LLMCompleter` the planner/responder
  use drives the loop; capped at 3 rounds to guarantee termination and bound LLM/DB work.
- **DI mirrors market/RAG**: real node only when `dashboard_service` is given; else the import-time
  module `graph` still compiles with a fail-soft default.

## How to verify
- `.venv/bin/python -m pytest tests/test_dashboard_tools.py tests/test_dashboard_agent.py -q`
- `.venv/bin/ruff check app/ tests/` · `.venv/bin/mypy app/agents/dashboard_agent.py app/tools/dashboard.py app/agents/graph.py`

## Tests (final step — mandatory)
- Full suite: `.venv/bin/python -m pytest -q` → **704 passed, 62 skipped** (green).
- New: `test_dashboard_tools.py` (11) — schemas OpenAI-shaped + no `status` arg, registry wiring,
  every propose tool writes `source="ai"`/`proposed`, read returns summary, graceful errors,
  per-user scoping. `test_dashboard_agent.py` (9) — propose flow lands `ai`/`proposed`, read-only
  turn summary, guest fail-soft (model never called, nothing written), unconfigured fail-soft,
  planner routes a "add these 5 tasks to my plan" turn to `[WorkerName.DASHBOARD]`, and a
  graph-level integration turn reaches the responder with a "proposed" summary.
- One stale test fixed at root cause (not weakened): `test_parallel_workers_fan_in_without_clobbering`
  asserted the dispatched worker set equals the full `WorkerName` enum; growing the enum required
  dispatching `DASHBOARD` too and excluding it from the citation-set assertion (it emits no citation
  by design). Fix reflects real behavior.
- Lint/format/type: `ruff check` clean; my files pass `ruff format --check`; `mypy` clean on all
  changed source. Note: `ruff format --check .` also flags **7 pre-existing P8-02 files**
  (`app/services/dashboard.py`, `app/repositories/dashboard_store.py`, `tests/test_dashboard_*`, …)
  with cosmetic signature-wrap drift — **not touched** (they belong to the separate P8-02 task; my
  P8-03 files are all format-clean). Flagging rather than reformatting another task's diff.

## Self-check
- [x] Meets acceptance criteria (intents/workers added + planner routing; 5 tools `source="ai"`;
  bounded node + guest fail-soft; `build_graph` kwarg + import-time default; `build_chat_service`
  wired; tool/node/planner/graph tests).
- [x] No secrets committed; Router→Service→Agent/Tool layering respected (tools/node depend on the
  `DashboardService`, never the store/DB directly).
- [x] Tests/lints pass (full suite green; ruff+mypy clean on changed files — see Tests note re:
  pre-existing P8-02 format drift).

## Response to review (revision 2)

Addressed the code review (`CHANGES_REQUESTED`); architecture review was already `APPROVED` (no changes needed there).

- **C1 (major) — read path never surfaced dashboard contents to the responder. FIXED.**
  `_summarize` now renders the `read_dashboard` payload into a text digest (via new
  `_render_dashboard_digest`) and folds it into `WorkerResult.content` — goals (with status /
  target_role / task-completion %), nested milestones + tasks, and the progress/streak rollup.
  Since the responder's `_worker_texts` grounds on `.content` only (never `.data`), the actual
  plan now reaches the user-facing answer, so an informational turn ("what's on my dashboard?")
  can be answered instead of returning a non-answer. `data` is unchanged (still `{read, proposed}`).
  New test `test_node_read_turn_folds_dashboard_data_into_content` seeds a goal + task, has the
  model call `read_dashboard`, and asserts both the goal title ("Become a data engineer") and task
  title ("Learn SQL") appear in `WorkerResult.content`.
- **C2 (nit) — `MilestoneCreate.model_validate(args)` relied on `extra="ignore"`. FIXED.**
  `ProposeMilestoneTool.run` now `args.pop("goal_id", None)` (goal_id addresses the parent goal —
  a service argument, not a `MilestoneCreate` field) before validating, so it no longer depends on
  pydantic's `extra="ignore"` default and stays correct even under `extra="forbid"`.
- **C3 (nit) — `_MAX_TOKENS = 512` risked truncating multi-tool-call generations. ADDRESSED.**
  Raised to `1024` (roomy for several parallel tool calls' `arguments` JSON plus a short wrap-up);
  comment updated to explain the intent.

### Verification (revision 2)
- `pytest tests/test_dashboard_tools.py tests/test_dashboard_agent.py -q` → **18 passed**.
- Full suite: `pytest -q` → **705 passed, 62 skipped** (was 704; +1 new read-content test).
- `ruff check` + `ruff format --check` clean on the changed files; `mypy` clean on
  `dashboard_agent.py` / `dashboard.py`. (Pre-existing P8-02 `ruff format` drift on 7 unrelated
  files is unchanged — still recommend a separate FIX task, not this diff's regression.)
