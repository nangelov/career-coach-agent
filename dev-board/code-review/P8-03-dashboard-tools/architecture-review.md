# Architecture review — P8-03-dashboard-tools · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | tools in `app/tools/`, agent in `app/agents/`, service in `app/services/` | `app/tools/dashboard.py`, `app/agents/dashboard_agent.py` over existing `app/services/dashboard.py` | none |
| A2 | §5.2 native tools (read + propose) | dashboard exposed as native `Tool`s the agent calls | 5 `Tool`s (read + propose goal/milestone/task + log progress), OpenAI-shaped schemas, `Tool`/`ToolRegistry` reuse | none |
| A3 | §5.2 never silent (propose→approve) | AI writes land as `proposed`, user approves via existing PATCH; `source=user\|ai` | every propose tool passes `source="ai"` only; `status` kept out of schemas; `DashboardService._resolve_status` resolves ai→proposed (single place) | none |
| A4 | §5.2 guests excluded (requires account) | guest cannot save a living plan | node fail-soft on `user_id is None` **before** any tool is built — model never called, no write path reachable | none |
| A5 | §3 planner→worker→responder | classified `Intent` routed to a fixed `WorkerName` worker, summary → responder | `Intent.DASHBOARD`/`WorkerName.DASHBOARD` added; `_INTENT_WORKERS`/`_INTENT_MAX_ITERATIONS` wired; enum auto-included in tool schema; `WorkerResult` framed as pending-approval | none |
| A6 | worker DI pattern | mirror `make_market_node`/`make_rag_node` (factory+closure, `build_graph` kwarg, import-time fail-soft default) | `make_dashboard_node(service=,router=)`, `build_graph(dashboard_service=)` binds real node else module default fails soft; `WORKER_NODES`/fan-in derive from enum | none |
| A7 | layering Router→Service→Agent/Tool | tools/node depend on `DashboardService`, not the store/DB | tools take `DashboardService`; node takes service+router; no store/driver reach-through | none |
| A8 | composition root | reuse `build_dashboard_service`, don't duplicate store wiring | `build_chat_service` reuses `build_dashboard_service(app)` (guarded on shared PG pool, mirrors `conversations`), injects service + shared `router` into `GraphTurnStreamer` | none |
| A9 | locked v2 (native tool-calling, no ReAct) | forced/native tool-calls, no text parser | bounded `tool_choice="auto"` loop against shared `LLMCompleter`; no ReAct parsing | none |
| A10 | phase fit | backend/agent wiring only; no P8-04 PDP-seed, no P8-05 UI, no new HTTP endpoints | none of those touched; approval reuses P8-02 PATCH | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Tool)
- [x] Honors locked decisions (native tool-calling, no ReAct; Postgres-anchored dashboard; shared LLM router; in-process posture unchanged)
- [x] Interfaces-before-implementations (`Tool`/`ToolRegistry`, `DashboardService`, `LLMCompleter` seams reused; per-turn `ToolRegistry`)
- [x] Budget posture respected (no new external deps; reuses existing OSS/self-hosted stack)

## Notes
- First **write-capable** worker in the graph (prior workers were retrieval-only). Safety is layered, not
  read-only: attribution/confirmation resolved once in the service (`source="ai"`→`proposed`), guest fail-soft in
  the node, and `user_id` closed over per-turn so the model can never spoof scope. Recorded as a durable ruling to
  template future agent write paths (P9 memory-learn).
- Attribution correctly kept out of the tool layer (no `status` in schemas) — the single `_resolve_status` seam
  stays authoritative (DRY/SoC). No follow-ups.
