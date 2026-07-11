---
name: project-phase-exit-verification
description: Blessed pattern for phase-exit (T) verification tasks — tests-only, cite prior tests, close only genuine gaps
metadata:
  type: project
---

Phase-exit `(T)` verification tasks (e.g. P2-08-verify) are **verification-only**: one new
test module, no product code / endpoints / schema / migrations.

**Why:** the exit criterion proves the phase's already-built blocks integrate end-to-end; it is
not a place to add product surface or redesign settled tasks.

**How to apply — the blessed posture (APPROVED bar):**
- Exercise the *real* production seams end-to-end (real `ChatService` + `PostgresConversationStore`
  + FastAPI router; `hybrid_search_chunks` + ORM `<=>`), injecting fakes only at the seams
  (`LLMRouter`, `EmbeddingClient` duck-type) — see [[project-hybrid-search]], [[project-conversation-persistence]].
- **Cite prior-task tests; close only genuine gaps.** P2-08 cited P2-07's service-layer restart test
  and closed its two real gaps (live Postgres + `POST /api/chat` router path) instead of duplicating it.
- Live-DB tests must **skip-not-fail** when Postgres is unreachable (keeps DB-less CI green — budget posture).
- Real 8B embedding model never loaded — constructed 4096-dim (`EMBEDDING_DIM`) fake vectors only.
- A weighting/behavior proof may exploit the real algorithm's edge (P2-08 used asymmetric RRF blends
  because 0.5/0.5 ties mirror-image ranks) — that *proves* the design, doesn't contradict it.

Self-contained per-file skip-fixtures/fakes (over a shared `conftest.py`) is the accepted
integration-suite convention here; don't require refactoring sibling suites into shared fixtures.

**Accepted deviations from tests-only (P4-10 rev 1, APPROVED):**
- A **mechanical `ruff format` reformat** of pre-existing gate-red files (incl. product code like
  `identity.py`) is acceptable *if* it is zero-logic (verify the diff — line-collapse only), **flagged
  in the report** (not silent), and needed to hand off with all CI gates green. Don't reject it; log a
  cheap "split into a cleanup commit" follow-up. Handoff-with-green-gates outranks strict tests-only.
- Faking the **planner LLM decision** via the P4-03 `build_graph(planner=)` seam to drive a *specific*
  route is the blessed way to prove routing e2e without live HF — the routing *mechanism* (Send fan-out,
  edges, fan-in) stays real; the real planner-from-LLM-output is proven separately in `test_agent_planner`.
  Composition across the two suites is complete; the live-HF planner path is a legitimate deferred
  live-infra pass. See [[project-agent-graph]].
