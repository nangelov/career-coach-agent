# Task P4-08-input-guardrails-minimal — Minimal input guardrails, wired for real

- **Phase:** P4   **Status:** ENG   **Tags:** (B)

## Scope

From `dev-board/tasks.md` P4:
> **(B)** Minimal input guardrails wired here (completed in P10).

The graph currently has an `input_guardrail_node` (P4-02) that is a **pass-through stub**: it always writes
`SafetyVerdict(allowed=True)` and the graph unconditionally proceeds to `memory_recall` regardless of the
verdict. This task makes the input guardrail **minimally real** — a fast, cheap heuristic check (not the full
P10 classifier) — and, critically, **wires its verdict into actual routing** so a disallowed turn short-circuits
before hitting the planner/workers/responder LLM calls, instead of just recording a verdict nobody acts on.

Full jailbreak/prompt-injection ML classification, PII scrubbing, and abuse/off-topic filtering are explicitly
**P10** scope (`dev-board/tasks.md` P10, design §7). This task is the minimal, cheap, deterministic slice that
makes the guardrail *mechanism* (verdict → routing decision → safe refusal) real end-to-end now, so P10 only
has to swap the detection logic, not build the plumbing.

## Implementation approach

- **Detection (minimal, deterministic — no LLM call, no new ML dependency):** a small, fast heuristic against
  `state.user_message` — e.g. a short deny-list/regex set of obvious jailbreak/injection phrases ("ignore
  (all|previous) instructions", "reveal your system prompt", "you are now DAN", etc.) and a basic length/empty
  guard (note `ChatRequest.message` already enforces `min_length=1`/`max_length=8000` at the schema layer —
  don't duplicate that, focus on content heuristics). Keep the list small, documented, and easy for P10 to
  extend/replace wholesale. Default-open on ambiguous input (minimize false positives — this is explicitly a
  coarse net, not the real classifier) but reliably catch the obvious/canonical jailbreak phrasing patterns a
  test suite would check for.
- **Routing (graph topology change — in scope for *this* task only):** add a conditional edge after
  `INPUT_GUARDRAIL` so that when `input_safety.allowed is False` the turn routes straight to a safe refusal
  path — either directly to `RESPONDER` (with the state carrying enough info for the responder to notice
  `input_safety.allowed is False` and return a fixed refusal message without calling the LLM/workers) or
  straight through `OUTPUT_GUARDRAIL` → `MEMORY_WRITER` → `END` with `AgentState.response` set to a canned
  refusal — engineer's call, document the choice, but the **planner and all workers must not run** for a
  blocked turn (no wasted LLM calls, no worker side effects, and it must not leak the guardrail's internal
  category list to the user). When allowed, behavior is unchanged (proceeds to `MEMORY_RECALL` as today).
- Update `input_guardrail_node`'s body (or introduce a small `guardrails/` heuristic module and call it from
  there — `dev-board/app-design-and-features.md` §8 already reserves `backend/app/guardrails/` for P10; you
  may create a minimal `app/guardrails/heuristics.py` now if it makes the P10 handoff cleaner, or keep it
  inline in the node — your call) to run the real check and populate `SafetyVerdict.allowed`/`categories`/
  `reason` accurately.
- Update the chat-graph integration from P4-07 (`ChatService`/`GraphTurnStreamer`) only if the routing change
  affects what it observes (e.g. it should still emit a normal `done` event with the refusal text — a blocked
  turn is not a server *error*, it's a successful turn with a policy answer; don't emit an `error` SSE event
  for this).

## Acceptance criteria

- [ ] A turn matching the heuristic deny-list is blocked **before** the planner/workers/responder LLM calls
      run (assert via a spy/mock that the injected router's `complete`/`stream` was never called for a
      blocked turn).
- [ ] `AgentState.input_safety` reflects the real verdict (`allowed=False`, non-empty `categories`, a `reason`)
      for a blocked turn, and `allowed=True` for a normal turn (no behavior change for legitimate turns).
- [ ] A blocked turn still produces a well-formed terminal `AgentState`/SSE `done` (not a raised exception, not
      an `error` event) with a safe, generic refusal — it must not echo the user's flagged content back
      verbatim in a way that could be seen as complying, and must not reveal the internal heuristic list.
- [ ] Graph topology change is minimal and localized to the input-guardrail conditional edge; the rest of the
      P4-02 topology (planner fan-out, worker fan-in, output guardrail, memory writer) is unchanged for the
      allowed path.
- [ ] Unit tests: representative blocked phrases short-circuit correctly (workers/responder LLM not called),
      representative legitimate messages are unaffected, an integration-style test through the real compiled
      graph (and ideally through `POST /api/chat` end-to-end, mirroring P4-07's real-endpoint test) proves the
      full block path.
- [ ] `ruff` + `mypy` clean; existing backend test suite (through P4-07) still green.

## Design references

- `dev-board/app-design-and-features.md` §7 "Security & Guardrails" — input guardrails list (jailbreak/
  injection, abuse/off-topic, PII) — this task implements a minimal slice of the first, full scope is P10.
- `dev-board/app-design-and-features.md` §3 — the graph diagram's `Guardrails` (input) node position.
- `dev-board/app-design-and-features.md` §8 — reserved `backend/app/guardrails/` location.
- `dev-board/code-review/P4-02-agent-graph/` — the existing `input_guardrail_node` stub + graph wiring this
  task extends with real routing.
- `dev-board/code-review/P4-07-chat-graph-integration/` — the live `POST /api/chat` path this now protects.
- `dev-board/tasks.md` P10 — the full guardrail task that replaces this heuristic with a real classifier.

## Constraints / non-goals

- Do NOT build the full P10 jailbreak/injection ML classifier, PII scrubber, or abuse/off-topic filter — a
  small deterministic heuristic only.
- Do NOT change `AgentState`'s shape (the `SafetyVerdict`/`GuardrailStage` types already exist from P4-01) or
  the P4-01 reducers.
- Do NOT change the planner/worker/responder node bodies themselves — only the input-guardrail node + its
  outgoing routing.
- Do NOT touch AuthZ/rate-limiting (P3-04) — this is a content-level check, not an access-control one.
- Keep the heuristic list small and clearly marked as a placeholder for P10, not a production-grade filter.
