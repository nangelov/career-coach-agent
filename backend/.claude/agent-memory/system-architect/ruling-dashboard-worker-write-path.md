---
name: ruling-dashboard-worker-write-path
description: Dashboard worker is a blessed WRITE-capable worker (propose-not-mutate); write safety = source="ai"→proposed in the service, guest fail-soft in the node
metadata:
  type: project
---

The P8-03 `DASHBOARD` worker extends the [[pattern-worker-node-di-scope]] shape into a **write path** — the
first worker that mutates user state, not retrieval-only. Blessed under §5.2 (native dashboard tools = read +
propose).

**Why:** §5.2/§8 explicitly design the dashboard as native tools the agent can read+write, gated by
propose→approve. The safety that makes a write-capable worker acceptable is layered, not the worker being
read-only:
- **Attribution lives in the service, once** (`DashboardService._resolve_status`: `source="ai"`→`status="proposed"`).
  Tools pass `source="ai"` only and never a `status` (kept out of the JSON schema) — no re-implementation in the
  tool layer (DRY). Never silent (§5.2 line 267, §risk-table line 714).
- **Guest exclusion enforced in the node before any tool is built** (`state.user_id is None` → fail-soft
  `WorkerResult.error`, model never called). §5.2 line 268: dashboard requires an account.
- **user_id closed over per-turn** (tools built by `build_dashboard_tools(user_id, service)`); the model supplies
  only args, never whose dashboard — can't spoof scope. This replaces the retrieval worker's "access allow-list".
- Bounded tool-calling loop (≤3 rounds) against the shared planner/responder `LLMCompleter`, fail-soft on `LLMError`.

**How to apply:** For future agent write paths (e.g. P9 memory-learn writes), require the same three seams:
attribution/confirmation resolved in the service (not the tool/node), per-turn scope closure (no model-supplied
user id), and guest/unconfigured fail-soft in the node. A worker that writes user state directly to a status the
user didn't approve, or resolves attribution in the tool layer, is a CHANGES_REQUESTED.

**Non-agent write path (P8-04 PDP seeding, blessed):** `services/pdp_seed.py` seeds the dashboard from a
generated plan via **service→service composition** — `PdpService` calls `DashboardService` with `source="ai"`
and never sets `status`, reusing the same attribution seam (no re-derivation). Blessed extension of the pattern.
Two deltas from the agent path are correct, not gaps: (1) no guest fail-soft branch is needed because PDP is an
**auth-only** endpoint (router 403s guests before `generate`), so `dashboard` is a required non-optional ctor arg;
(2) the prose→rows extraction is a **deterministic parser, never a 2nd LLM pass** (budget). Service→service reuse
of another service's attribution resolution (vs re-deriving source/status) is the accepted shape — don't flag it.
