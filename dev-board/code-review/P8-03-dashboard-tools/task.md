# Task P8-03-dashboard-tools — Expose the dashboard as native tools (read + propose)
- **Phase:** P8   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P8 item: "Expose dashboard as **native tools** (read + propose); AI writes
user-scoped, `source=ai`, confirmable (proposed → approved), never silent."

Wire the P8-02 `DashboardService` into the multi-agent chat graph as a new worker so the
assistant can, mid-conversation, read the user's dashboard and **propose** goals/milestones/
tasks/progress notes ("add these 5 tasks to my plan"), never write silently.

### Architecture (mirrors existing patterns already in the codebase — do not invent a new shape)
This app already has the `Tool` / `ToolRegistry` abstraction (`app/tools/base.py`) for
JSON-schema, LLM-callable tools — used today only by `current_date_and_time` /
`internet_search`, which are not yet wired into the graph via real tool-calling. The planner
(`app/agents/planner.py`) already demonstrates the "schema-in / structured-out, forced
tool-call, no ReAct parsing" contract (locked decision, CLAUDE.md). The multi-agent graph
(`app/agents/graph.py`, `app/agents/state.py`) routes the planner's classified `Intent` to a
fixed `WorkerName` worker (see `market_intel_node` / `app/agents/market_agent.py` for the
closest analog: a request-path worker built via a `make_*_node(...)` factory, bound to
injected collaborators via `build_graph(...)` kwargs, falling back to a dependency-free
default at import time).

Follow that same shape for the dashboard:

1. **`app/agents/state.py`** — add `Intent.DASHBOARD` (the user is asking about / wants to
   change their plan: "what's on my dashboard", "add these tasks to my plan", "mark X done",
   "log today's progress") and `WorkerName.DASHBOARD` to the existing enums.
2. **`app/agents/planner.py`** — add `Intent.DASHBOARD` to the tool-schema `enum`, the prompt's
   intent list, `_INTENT_WORKERS` (→ `[WorkerName.DASHBOARD]`), and `_INTENT_MAX_ITERATIONS`.
3. **`app/tools/dashboard.py`** — new native `Tool` implementations over the P8-02
   `DashboardService` (`app/services/dashboard.py`): a read tool (list goals/milestones/tasks/
   recent progress — reuse `DashboardService.get_summary`) and propose tools (propose a goal,
   propose a milestone under a goal, propose a task under a goal, log a progress note). Every
   propose tool **must** call the service with `source="ai"` (which the service already resolves
   to `status="proposed"` — do not let a tool pass `status` directly). Because `Tool.run()`'s
   signature takes only the parsed arguments (no per-request context), these tools are
   **constructed per turn**, closing over the caller's `user_id` and the shared
   `DashboardService` — mirror how `market_agent.py` / `rag_agent.py` bind collaborators into a
   node closure, just one level down (tool closes over `user_id`, node closes over the service).
   A guest (`user_id is None`) must never reach a tool that can write — see point 4.
4. **`app/agents/dashboard_agent.py`** — new `make_dashboard_node(...)` factory (mirrors
   `make_market_node` / `make_rag_node`): builds a per-turn `ToolRegistry` with the P8.3 tools
   bound to `state.user_id`, then drives a small, **bounded** (e.g. max 3 iterations) tool-calling
   loop against the injected `LLMCompleter` (the same router the planner/responder use) so the
   model can call zero or more dashboard tools based on `state.user_message` (and the planner's
   `steps`), then produces a `WorkerResult` summarizing what was read and/or proposed (e.g. "I
   added 3 tasks to your 'Become a data engineer' goal — review and approve them on your
   dashboard."). **Guests** (`state.user_id is None`): fail soft with a `WorkerResult.error`
   pointing at "sign in to use the dashboard" — never call a tool, never crash the graph (§5.2:
   "Guests: dashboard requires an account").
5. **`app/agents/graph.py`** — register the new `WORKER_NODES` member is automatic (derived from
   `WorkerName`); add the node in `build_graph` mirroring the RAG/market resolution pattern
   (`dashboard_service: DashboardService | None = None` kwarg → bind into
   `make_dashboard_node(...)` when given, else a dependency-free default that fails soft).
6. **`app/bootstrap.py` / `app/services/chat.py`** — thread a `DashboardService` (built the same
   way `build_dashboard_service` does for the HTTP router — reuse it, do not duplicate) into
   `build_chat_service`'s `GraphTurnStreamer(...)` construction, so the live chat endpoint can
   actually route to the dashboard worker.

**Never silent (task acceptance).** Every AI write goes through `DashboardService` with
`source="ai"`, which the service already resolves to `status="proposed"` — nothing in this task
should bypass that or write `status` directly. The responder's synthesized answer should tell
the user something was **proposed** and needs approval (existing `PATCH .../goals|milestones|
tasks` endpoints from P8-02 are how the user approves/rejects — no new approve endpoint).

## Acceptance criteria
- [ ] `Intent.DASHBOARD` / `WorkerName.DASHBOARD` added; planner routes dashboard-flavored turns
      to the new worker (unit test: a "add these tasks to my plan" style turn classifies to
      `DASHBOARD` and routes to `[WorkerName.DASHBOARD]`).
- [ ] `app/tools/dashboard.py`: read tool + propose-goal/milestone/task/progress tools, each with
      a proper OpenAI-shaped JSON schema; every propose tool writes `source="ai"` only.
- [ ] `app/agents/dashboard_agent.py`: `make_dashboard_node` — bounded tool-calling loop, guest
      fail-soft, produces a `WorkerResult` (content + `data` + citations if relevant).
- [ ] `build_graph(...)` accepts a `dashboard_service=` kwarg and wires the real node when given;
      falls back to a dependency-free default at import time (module-level `graph` still compiles
      without one).
- [ ] `build_chat_service` wires a real `DashboardService` into the graph so `POST /api/chat` can
      exercise the full path end-to-end.
- [ ] Tests: planner routing, tool unit tests (in-memory `DashboardStore`), dashboard-node tests
      (fake `LLMCompleter` emitting tool calls, asserting `source="ai"`/`proposed` writes and
      guest fail-soft), and at least one graph-level integration test proving a dashboard turn
      reaches the responder with a sensible summary.

## Design references
- dev-board/app-design-and-features.md §5.2 "Dashboard — the living Personal Development Plan"
  (native tools, propose→approve, guests excluded), §3 (planner/worker/responder shape).
- dev-board/plan.md Phase 8.
- Patterns to mirror: `backend/app/agents/planner.py` (schema-in/structured-out, no ReAct),
  `backend/app/agents/market_agent.py` + `make_market_node` (request-path worker,
  `build_graph` DI kwarg resolution), `backend/app/tools/base.py` (`Tool`/`ToolRegistry`),
  `backend/app/services/dashboard.py` (already resolves `source="ai"` → `proposed` — reuse
  verbatim, do not re-implement attribution logic in the tool layer).

## Constraints / non-goals
- No new HTTP endpoints (approve/reject is already "PATCH/DELETE a proposed row" from P8-02).
- No PDP-seeding logic here (P8-04) and no frontend UI here (P8-05) — backend/agent wiring only.
- Do not touch the P1 `current_date_and_time` / `internet_search` tools beyond reusing the
  `Tool`/`ToolRegistry` abstraction they already established.
