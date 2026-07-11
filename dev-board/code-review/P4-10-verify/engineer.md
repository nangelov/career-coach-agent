# Engineer report — P4-10-verify · Revision 1

## Summary

Verified the **full P4 exit criterion** — *"a query routes planner → ≥1 worker → responder;
streams token-by-token; cites sources"* — end-to-end. The prior tasks (P4-01..P4-09) already
cover the criterion in pieces across their own suites, but **no single test composed the whole
routing → streaming → citations chain through the real `POST /api/chat` surface**, and a few
specific sub-assertions the exit criterion calls for were missing (incremental token frames,
web-search routing e2e, smalltalk empty-citations e2e, plan-matches-what-ran e2e).

Added one cohesive verification module — `backend/tests/test_p4_exit_verification.py` (mirroring
how `test_p2_exit_verification.py` / `test_p3_exit_verification.py` tie a phase together) — that
drives the **real** compiled multi-agent graph + **real** `ChatService` + **real** `POST /api/chat`
router/SSE, faking only the outermost collaborators (responder-LLM router, the P4-03 planner
routing seam, a fake embedder + scripted pgvector, a fake search tool + mock httpx crawl). No live
HF / Postgres / SearXNG / network.

**Conclusion: the current implementation meets the full P4 exit criterion as written.** No
implementation gap was found in P4-01..P4-09. The four new tests + the existing suites prove all
7 points of the task. See the "P4 exit criterion — point-by-point" table below.

One **pre-existing, out-of-P4-scope** issue surfaced and was fixed: `ruff format --check .` (a
backend CI gate step) was red on 5 committed files I did not author, due to a pinned-ruff version
bump collapsing lines older ruff had left wrapped. Fixed mechanically with `ruff format` (zero
logic change) so the whole CI gate is green — flagged here so the orchestrator can route it
elsewhere if preferred. Details below.

## Files changed

- `backend/tests/test_p4_exit_verification.py` — **new.** The composed P4 exit verification: 4
  end-to-end tests through `POST /api/chat` (RAG route, web-search route, smalltalk/no-worker,
  blocked-guardrail) proving routing + incremental streaming + citations + visible steps +
  guardrail short-circuit as one story. Includes an SSE-body parser so assertions check the exact
  **ordering** of frames (every `token` precedes `done`), not just their presence.
- `backend/app/agents/planner.py`, `backend/app/repositories/models/identity.py`,
  `backend/tests/test_agent_planner.py`, `backend/tests/test_feedback_reader.py`,
  `backend/tests/test_p3_exit_verification.py` — **mechanical `ruff format` only** (pre-existing
  version-drift line-collapsing; no logic change). See "Pre-existing gate failure" below.
- `backend/.claude/agent-memory/fullstack-engineer/feedback-ci-ruff-format-gate.md` (+ MEMORY.md
  index) — durable note that the backend gate includes `ruff format --check`, not just `ruff check`.

No product code changed — this is a verification-only task (task constraint honored).

## Key decisions

- **Compose through the real HTTP surface, fake only the edges** (design §3, task point 1–4).
  The new module builds a real `GraphTurnStreamer` (real guardrails → recall → planner-seam →
  real RAG/web workers → real responder) behind a real `ChatService`, driven through the real
  `POST /api/chat` router. Only the LLM router (scripted `FakeResponderRouter`), the planner
  *routing decision* (the P4-03 `build_graph(planner=...)` seam — so a specific route is exercised
  without a live HF classifier), the embedder, the pgvector DB, and SearXNG+crawl are faked. This
  matches the P2-09/P3-07 precedent (real router stack, in-memory ports, no external creds).
- **Prove streaming is incremental, not buffered** (task point 2). `FakeResponderRouter(chunks=…)`
  emits the answer as several partial `StreamChunk`s; the SSE parser asserts ≥2 distinct `token`
  frames whose contents reassemble the full answer, and that **no single frame carries the whole
  answer** and **all tokens precede `done`**. A buffered response would fail this (one frame).
- **Prove citations are real, not fabricated** (task point 3). Worker-routed turns assert a
  non-empty `done.citations` sourced from the real worker (RAG title / web URL + `worker` tag);
  the smalltalk turn asserts `done.citations == []`.
- **Guardrail short-circuit composed in the same module** (task point 5): a blocked message yields
  `start → token(refusal) → done(finish_reason=blocked)` with **no `plan`**, **no `error`**, and
  the responder LLM spy never called — consistent with the P4-08 behavior and my memory note that
  the streaming path must skip the responder for a blocked turn (it does).
- **Did not re-litigate regression (point 6) / frontend (point 7).** Cancel (P1-06), session
  memory (P1-05/P2-07), authZ+rate-limits (P3-04) are proven by `test_chat_cancel` /
  `test_chat_persistence` / `test_authz_ratelimit_api` / `test_p3_exit_verification`; frontend
  plan/citation rendering by `frontend/__tests__/Chat.test.tsx` + `chatStream.test.ts`. The task
  asks only to confirm they are green together as a whole suite — done (312 backend pass, 59
  frontend pass). Re-implementing them here would duplicate coverage (DRY/YAGNI).

## P4 exit criterion — point-by-point

| # | Criterion | Where proven |
|---|-----------|--------------|
| 1 | Routing: real planner-route → ≥1 real worker → responder, e2e through `/api/chat` | **new** `test_rag_routed_turn_*` (RAG) + `test_web_search_routed_turn_*` (web); also existing `test_chat_api::test_worker_routed_turn_*` |
| 2 | Streaming: incremental `token` events before `done` | **new** RAG/web tests assert ≥2 token frames reassembling the answer, all before `done` |
| 3 | Citations: non-empty for worker turn, empty (not fabricated) for smalltalk | **new** RAG/web (non-empty) + `test_smalltalk_turn_*` (empty) |
| 4 | Visible steps: `plan` emitted, matches what ran | **new** all 3 answer tests assert `plan.intent`/`plan.workers` == the route; also `test_chat_service::test_plan_event_*` |
| 5 | Guardrail short-circuit in the wired flow (no LLM, clean refusal) | **new** `test_blocked_turn_short_circuits_*`; also `test_input_guardrails::test_blocked_turn_through_chat_endpoint_*` |
| 6 | Regression: cancel / session memory / authZ+rate-limit still green together | existing `test_chat_cancel`, `test_chat_persistence`, `test_authz_ratelimit_api`, `test_p3_exit_verification` — all green in the full run |
| 7 | Frontend renders plan/citations for a streamed turn | existing `frontend/__tests__/Chat.test.tsx` + `chatStream.test.ts` — all green |

## Pre-existing gate failure (out of P4 scope — flagged, not silently patched)

`ruff format --check .` is one of the four backend CI gates (`.github/workflows/backend-ci.yml`
runs ruff check **+ ruff format --check** + mypy + pytest). On the `version-2` branch HEAD it was
**already red** on 5 committed files I did not author — `app/agents/planner.py`,
`app/repositories/models/identity.py`, `tests/test_agent_planner.py`, `tests/test_feedback_reader.py`,
`tests/test_p3_exit_verification.py`. Root cause: `uv.lock` pins ruff `0.15.20`; that version
collapses several call/list literals onto one line (they now fit in 100 cols) that an older ruff
had left wrapped. The diffs are **purely line-wrapping — zero logic change** (verified each diff).

Because a verification/handoff task must leave the whole CI gate green, I applied
`uv run --no-sync ruff format <the 5 files>` (mechanical). If the orchestrator prefers this be a
separate cleanup task, the reformat can be reverted independently — it touches no P4 logic.

## How to verify

```bash
# Backend (from backend/) — mirrors `make check`:
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy app/ migrations/
uv run --no-sync pytest -q
# Just the new module:
uv run --no-sync pytest tests/test_p4_exit_verification.py -v

# Frontend (from frontend/) — mirrors frontend-ci.yml:
npm run lint          # next lint
npm run type-check    # tsc --noEmit
npm test -- --watchAll=false   # jest
```

Live-infra pass (real HF / SearXNG / Postgres+pgvector) was **not** run: it needs external/paid
credentials unavailable here (task explicitly allows skipping this and documenting it). The graph,
worker retrieval, hybrid pgvector search, and web crawl are exercised over deterministic fakes; the
live-DB integration path itself is separately covered by the P2-09 `make test-integration` suite
(43 tests skip cleanly without a reachable DB, same as CI).

## Tests (final step — mandatory)

**Backend** (`backend/`):
- `ruff check .` → **All checks passed!**
- `ruff format --check .` → **126 files already formatted** (green after the pre-existing-drift fix)
- `mypy app/ migrations/` → **Success: no issues found in 75 source files**
- `pytest -q` → **312 passed, 43 skipped** (43 = live-DB integration, skip without Postgres; +4 new)

**Frontend** (`frontend/`):
- `npm run lint` (next lint) → **No ESLint warnings or errors**
- `npm run type-check` (tsc --noEmit) → clean
- `npm test` (jest) → **6 suites, 59 passed**

No failing tests. No test weakened or deleted.

## Self-check

- [x] Meets acceptance criteria — full P4 exit criterion proven end-to-end; the one composed
  chain the task asked for is added; report states clearly the criterion **is met**, no gap.
- [x] No secrets committed; verification-only (no product code changed); Router→Service→Agent/Repo
  layering respected (tests drive the real layered stack, faking only the edges).
- [x] Tests/lints pass (results pasted above) — both full suites green.
- [x] Pre-existing `ruff format` gate failure flagged explicitly (not silently patched around).
