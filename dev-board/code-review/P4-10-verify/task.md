# Task P4-10-verify — P4 exit verification

- **Phase:** P4   **Status:** ENG   **Tags:** (T)

## Scope

tasks.md item: "A query routes through planner → ≥1 worker → responder; streams; shows citations."

This is the phase-level integration verification pulling together P4-01..P4-09 (state, graph wiring, planner,
RAG worker, web-search worker, responder, the `POST /api/chat` graph integration, minimal input guardrails,
and the frontend plan/citation rendering). Write/verify end-to-end tests (or a documented manual verification,
matching how P2-08/P2-09 and P3-07 verify tasks were handled) proving the full P4 exit criterion:

1. **Routing:** a representative query (e.g. a career/knowledge-base question) is classified by the real
   planner, routed to ≥1 real worker (at minimum RAG; web-search too if practical), and reaches the responder
   — end-to-end through `POST /api/chat`, not just at the individual-node level already covered by P4-01..06's
   own unit/integration tests.
2. **Streaming:** the answer streams token-by-token over SSE (assert incremental `token` events arrive before
   `done`, not one big buffered chunk).
3. **Citations:** the terminal `done` event carries non-empty `citations` for a worker-routed turn, and is
   empty (not fabricated) for a smalltalk/no-worker turn.
4. **Visible steps:** the `plan` event (intent/steps/workers) is emitted and matches what actually ran.
5. **Guardrail short-circuit still works** in the now-fully-wired flow: a blocked-heuristic message (P4-08)
   does not reach the planner/workers/responder LLM calls and still produces a clean `done` with a safe
   refusal.
6. **Regression check:** cancel (P1-06), session memory (P1-05/P2-07), and AuthZ/rate-limiting (P3-04) still
   work against the graph-driven turn (P4-07 already added targeted tests for these — this task's job is to
   confirm they're still green together as a whole suite, not to re-litigate them individually).
7. **Frontend:** the P4-09 UI renders plan/citation info for a real (or realistically mocked) streamed turn
   — confirm via the existing/extended frontend test suite; a full live browser click-through is not required
   if the automated coverage already proves the contract.

## Acceptance criteria

- [ ] All points above are covered by automated tests (preferred — most already exist across P4-01..P4-09;
      this task's job is to confirm they compose end-to-end, and add the one or two integration tests that
      specifically prove the *full* routing → streaming → citations chain through the real `POST /api/chat` if
      no existing test already does, e.g. building on P4-07's
      `test_worker_routed_turn_streams_tokens_and_cites_end_to_end`) or a clearly documented manual
      verification script/checklist for any part that genuinely requires a live HF endpoint/Postgres/SearXNG
      (mirroring how P2-09's live-DB-gated tests are documented and run via `make test-integration`).
- [ ] Full backend test suite green (`ruff`, `mypy`, `pytest`).
- [ ] Full frontend test suite green (`lint`, `tsc`, `jest`).
- [ ] If a live-infra verification pass is warranted (real HF models / real SearXNG / real Postgres+pgvector),
      run it the same way P2-09 documented (`docker compose up -d db` etc. as applicable) and report the
      result — but do not block this task on infra that requires paid/external credentials unavailable in
      this environment; document what was and wasn't feasible to run live.
- [ ] Report clearly states: does the current implementation meet the full P4 exit criterion as written?  If a
      gap is found, flag it in the report rather than silently patching around it, so the orchestrator can
      route a fix to the right prior P4 task (this task's job is to prove — or precisely characterize the gap
      in — the exit criteria, not to redesign prior tasks).

## Design references

- `dev-board/plan.md` — P4 exit criterion: "a query routes planner → ≥1 worker → responder, streams, and
  cites sources."
- `dev-board/app-design-and-features.md` §3 — the full graph this phase implements.
- `dev-board/code-review/P4-01-agent-state/` through `P4-09-frontend-plan-citations/` — everything under
  verification here.

## Constraints / non-goals

- This task should not introduce new endpoints/features — it's verification of P4-01..P4-09's work. If a gap
  requires real implementation changes, flag it rather than silently patching around it.
- Do not weaken or delete existing tests to make the suite "pass" — if something is genuinely broken, report
  it as a gap.
