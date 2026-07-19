# Architecture review — P10-05-rate-limits-per-ip-tool · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | new code in the right modules | IP resolver in `security/client_ip.py`; policy in `services/rate_limiting.py`; per-tool seam in `tools/base.py`; deps in `security/dependencies.py`; wiring in `bootstrap.py`/`agents/graph.py`/`agents/dashboard_agent.py`; settings in `config.py` | none |
| A2 | Reuse port, no fork (task constraint / §7.5) | extend `RateLimiter`/`RedisRateLimiter`, not a 2nd mechanism | IP + tool are new `RateLimitAction` namespaces + policy methods (`enforce_ip`, `check_tool`) over the same fixed-window `hit()` port; Redis adapter untouched | none |
| A3 | Layering (Router→Service→Agent/Repo) | services must not depend on tools/agents; per-tool policy in service | `SessionToolRateLimiter` **structurally** satisfies `tools.base.ToolInvocationLimiter` (Protocol lives in tools layer); service never imports tools. Agent types `RateLimitService` under `TYPE_CHECKING` only, receives the concrete limiter via the port (consistent with the existing `DashboardService` injection idiom) | none |
| A4 | §7.5 trusted-proxy XFF read | header honored only behind an allowlisted peer; unspoofable | `ClientIpResolver` walks XFF right-to-left past trusted hops; untrusted/unconfigured peer → header ignored, direct peer used. Default allowlist empty = XFF never trusted (safe on bare bind) | none |
| A5 | §7.5 abuse handling — graceful degrade | per-tool hit must not crash the graph | `check_tool` never raises; `ToolRegistry.execute` turns a denial into a `ToolResult.error` tool message the model wraps up on; per-IP over-budget → clean `429` + `Retry-After` | none |
| A6 | DRY enforcement point | single per-tool chokepoint | enforced at `ToolRegistry.execute`, so any current/future model-driven tool loop inherits the cap by injecting a limiter | none (see Note N1) |
| A7 | AuthZ-first ordering (§7) | reject cross-session before spending budget; identity from token not body | `authorize_session_access` runs before `enforce_ip`/`enforce`; turn `user_id` taken from verified token | none |
| A8 | S9/P12 boundary | no Altcha/PoW/global budget breaker here | none built; distinction documented in `engineer.md`, config, and docstrings | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo) — services stay tools-agnostic via a structural port
- [x] Honors locked decisions — Postgres+Redis only (Redis fixed-window counters), no new store, no ReAct parser touched
- [x] Interfaces-before-implementations — `ToolInvocationLimiter` Protocol + `RateLimiter` ABC seams; concrete adapters injected
- [x] Budget posture respected — free/OSS/self-hosted (Redis), generous caps configurable via settings

## Notes
- N1 (follow-up, not blocking): the per-tool limiter is wired only into the dashboard worker today — the only current model-driven tool loop. Future model-driven loops (P6 market-intel crawl trigger, web search worker) must pass a `rate_limiter` into their `ToolRegistry` to inherit the cap. The seam is uniform, so this is a one-line injection when those loops land; scope for this task ("today: the dashboard worker") is correct.
- N2 (nit): the `rate_limiting.py` module-level docstring still frames the module as "per-session / per-tool" and quotes §7 without mentioning the new per-IP layer; cheap to refresh next time the file is touched.
