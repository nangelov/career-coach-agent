# Task P1-09-verify — P1 exit criteria: chat/tool/stream/stop/failover; no ReAct parser
- **Phase:** P1   **Status:** ENG   **Tags:** (T)

## Scope
This is the **P1 exit-criterion verification task**, covering the two remaining `(T)` items in
`dev-board/tasks.md`'s P1 section:
1. Manual: chat → tool call → token stream → stop. Kill primary model → fails over to next.
2. Confirm no ReAct parser exists in the new backend path.

Verify the walking-skeleton exit criteria from `dev-board/plan.md` Phase 1: *"a user can chat, the model
calls a tool, the answer streams token-by-token, stop works, and killing the primary model endpoint
transparently fails over. `output_parser.py` is gone."*

The engineer must:

1. **Run the full backend test suite** (`ruff check .`, `ruff format --check .`, `mypy app/`, `pytest -q`)
   from `backend/` and confirm everything is green — this is the regression baseline before further manual
   checks.
2. **Live/manual verification, if a real HF token + running Redis are available in this environment** (per
   `docker-compose.yml` from P0, or `uvicorn app.main:app` + a local Redis): drive one real conversation
   turn through `POST /api/chat` that provokes a tool call (e.g. "what's the date and time right now?"),
   confirm tokens stream incrementally, then start a second longer turn and call
   `POST /api/chat/{session}/cancel` mid-stream, confirming a clean `cancelled` terminal event.
3. **Failover verification.** Killing the *actual* primary HF model endpoint isn't something you control
   directly (it's a third-party service) — instead, verify failover the way the codebase already proves it:
   point `LLM_PRIMARY_MODEL`/`LLM_MODELS` at a deliberately invalid/unreachable model id (or otherwise force
   the primary to fail — e.g. a bad base URL override for just the primary slot, if the router's config
   supports per-model overrides; check `app/config.py` and `app/llm/router.py` first) and confirm a live
   `POST /api/chat` call still succeeds by falling over to the secondary. If a live HF token isn't available
   in this environment, this step may fall back to **re-confirming the existing automated router tests**
   (`tests/test_llm_router.py` — primary-timeout-then-secondary-serves, mid-stream-resume) as the evidence,
   and clearly document that no live network check was possible here (same posture P0-11-verify took for
   Docker-unavailable checks).
4. **Confirm `output_parser.py` (or any ReAct text-parsing) does not exist anywhere in the v2 backend path.**
   Grep `backend/app/` for ReAct-parser patterns (`Action:`, `Final Answer:`, `ReActSingleInputOutputParser`,
   `FlexibleOutputParser`, `PDPOutputParser`, references to `legacy-code`'s `output_parser.py`, etc.) and
   confirm zero hits outside `legacy-code/` (the intentionally-preserved, unused v1 reference copy — see
   `dev-board/tasks.md` P0 "Clean up"). Document the exact grep commands + empty/expected output.
5. **Confirm the frontend chat page (P1-08) end-to-end against a running backend**, if feasible in this
   environment (`npm run build` at minimum; a live click-through if a browser/dev server is available)
   — otherwise document what was and wasn't checkable here.
6. **Fix any issues found** during verification (minimal, targeted fixes only — this is not a place to add
   new features). If something can't be fixed or verified live in this environment, document precisely why
   and what the expected/tested-via-automation behavior is instead.
7. Write a **verification report** in `engineer.md` with the exact commands run and their real outputs
   (copy-paste, not placeholders) — same standard as `P0-11-verify/engineer.md`.

## Acceptance criteria
- [ ] `ruff check .`, `ruff format --check .`, `mypy app/`, and `pytest -q` all pass from `backend/` (paste
      output).
- [ ] Either a live SSE trace showing chat → tool call → streamed tokens → stop/cancel working end-to-end,
      OR a clear, documented explanation of what couldn't be run live here plus the automated-test evidence
      that covers the same behavior.
- [ ] Either a live failover demonstration (forced-bad primary → secondary serves) OR a documented
      equivalent via `tests/test_llm_router.py`, clearly labeled which one was actually performed.
- [ ] A grep-based audit proves no ReAct/`output_parser`-style text parsing exists in `backend/app/`
      (excluding `legacy-code/`).
- [ ] `engineer.md` contains actual command outputs, not placeholders, and clearly distinguishes "verified
      live" from "verified via existing automated tests" for each exit criterion.

## Design references
- dev-board/plan.md: Phase 1 exit criteria (walking skeleton)
- dev-board/tasks.md: P1 `(T)` verify bullets; P0 "Clean up" (legacy-code preserved but unused)
- dev-board/code-review/P1-04-chat-endpoint/engineer.md, P1-05-session-memory/engineer.md,
  P1-06-cancel-stream/engineer.md, P1-07-message-id/engineer.md, P1-08-frontend-chat/engineer.md — what's
  actually implemented and how each already documented its own verification
- dev-board/code-review/P0-11-verify/engineer.md — the precedent format/rigor for a verification-only task

## Constraints / non-goals
- Do not add new features — only fix what's broken to meet the P1 exit criteria, and document what genuinely
  cannot be exercised live in this environment (e.g. no real HF token/network egress).
- Do not re-review code line-by-line (that already happened per-task in P1-01…P1-08's parallel reviews) —
  this task is about proving the **integrated** exit criteria hold, not re-litigating individual diffs.
- If Docker/HF-network/browser aren't available in this sandboxed environment, that's fine — document
  clearly what evidence substitutes for a live check (same posture P0-11-verify took for Docker).
