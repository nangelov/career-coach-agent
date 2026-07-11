# Architecture review — P4-10-verify · engineer revision 1

## Verdict: APPROVED

## Design conformance

| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | P4 exit criterion — routing (plan.md P4 §exit; design §3) | "a query routes planner → ≥1 worker → responder" e2e through `POST /api/chat` | `test_rag_routed_turn_*` + `test_web_search_routed_turn_*` drive the **real** `GraphTurnStreamer` (real `route_after_planner` Send fan-out, real RAG/web worker nodes, real responder) behind real `ChatService` + real router/SSE; only the planner *decision* is injected via the blessed P4-03 `build_graph(planner=)` seam | none — routing mechanism (conditional fan-out, worker→responder fan-in) is real; see Note 1 on the injected classification |
| A2 | P4 exit — streaming (plan.md; §3 "streams tokens") | incremental `token` frames before `done`, not one buffer | Asserts ≥2 distinct `token` frames, all indices < `done_idx`, reassembling the full answer, and **no single frame == whole answer**; `done` is terminal | none |
| A3 | P4 exit — citations (§3 "cite sources") | non-empty for worker turn; empty (not fabricated) for smalltalk | RAG asserts `title`+`worker` tag; web asserts `url`+`worker`; smalltalk asserts `done.citations == []` — sourced from the real workers over scripted data | none |
| A4 | Visible steps (plan.md "surfaces planner/worker steps") | `plan` event emitted, matches what ran | All three answer tests assert `plan.intent`/`plan.workers` == the exercised route, once, before the first token | none |
| A5 | Guardrail short-circuit in wired flow (§7; P4-08) | blocked msg skips planner/workers/responder LLM, clean refusal | `test_blocked_turn_*`: no `plan`, no `error`, responder spy `stream_messages == [] and complete_messages == []`, `done.finish_reason == "blocked"`, refusal does not echo flagged input | none |
| A6 | Regression (#6) — cancel/session/authZ (P1-06/P2-07/P3-04) | confirm green together, do not re-litigate | Cited to `test_chat_cancel` / `test_chat_persistence` / `test_authz_ratelimit_api` / `test_p3_exit_verification`; whole suite green | none — correct per task (not re-implemented → DRY/YAGNI) |
| A7 | Frontend (#7) — plan/citation render (P4-09) | existing suite proves the contract | Cited to `Chat.test.tsx` + `chatStream.test.ts` (59 frontend pass) | none — regression cited, not new work |
| A8 | Target structure / layering (§8) | tests exercise real Router→Service→Agent stack, no product surface added | New module `backend/tests/test_p4_exit_verification.py` only; faked at the outermost edges (LLM router, embedder, pgvector, search+crawl) — matches blessed phase-exit posture | none |
| A9 | Verification-only / no scope creep (task constraint; plan.md) | no new endpoints/features/schema/migrations | Confirmed: only a new test module + a mechanical `ruff format` reformat of 3 committed files + memory notes | Note 2 — reformat of `identity.py` (product) is a minor tests-only deviation, flagged & cosmetic → logged follow-up |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — drives the real layered stack (router → `ChatService` → graph → workers/responder), fakes only edges.
- [x] Honors locked decisions — no ReAct parser; LangGraph graph exercised as-is (matches the blessed §3 topology); in-process embeddings faked via `EmbeddingClient` duck-type (real 8B model never loaded); no MongoDB; SSO-only auth untouched.
- [x] Interfaces-before-implementations — fakes stand in at real seams (`LLMResponder`/`EmbeddingClient`/`SearchRunner`/`build_graph(planner=)`), no new interfaces invented.
- [x] Budget posture respected — no live HF/Postgres/SearXNG/network; live-infra pass explicitly deferred (paid/external creds), consistent with P2-09.

## Verification performed by this review
- Ran `pytest tests/test_p4_exit_verification.py -v` → **4 passed** (the load-bearing new evidence is real, not asserted).
- Ran full `pytest -q` → **312 passed, 43 skipped** (matches the report; 43 = live-DB skip-not-fail).
- Ran `ruff format --check .` → **126 files already formatted**; `ruff check .` → **All checks passed** (CI gate green).
- Inspected `git diff` of the flagged product file `identity.py` → confirmed **pure line-collapse, zero logic change**.

## Notes

1. **The one thing not proven purely e2e is the real planner LLM classification.** The tests inject a
   fixed `PlannerDecision` via the P4-03 `build_graph(planner=)` seam rather than running a live HF
   classifier. This is correct and consistent with the blessed budget posture (fake the LLM at the edge)
   and with my prior ruling on the P4-02 graph — the *routing mechanism* (Send fan-out, conditional
   edges, fan-in) is fully real, and the real planner node body producing a route from LLM output is
   proven in isolation by `test_agent_planner`. Composition is therefore complete **across** the two
   suites. Not a gap; the live-HF planner path is legitimately deferred to a live-infra pass (same
   treatment P2-09 gave live Postgres).

2. **Follow-up (cheap, cosmetic, correctly flagged):** to keep the `ruff format --check` CI gate green,
   the engineer reformatted 3 already-committed files it did not author (`app/repositories/models/identity.py`
   [product], `tests/test_feedback_reader.py`, `tests/test_p3_exit_verification.py`) — a mechanical
   line-collapse forced by the pinned `ruff 0.15.20` bump, zero logic change (verified). This is a
   minor deviation from the tests-only posture of a (T) verification task, but it was flagged in the
   report (not silently patched), it is trivially revertible, and leaving the gate red would violate
   the handoff requirement that a verification task hand off with all gates green. **Accepted as-is.**
   Orchestrator's option: split the reformat into a separate cleanup commit for a cleaner history — not
   a blocker.
