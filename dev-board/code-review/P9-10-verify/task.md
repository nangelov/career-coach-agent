# Task P9-10-verify — P9 exit: cross-session adaptation; 👎 changes behavior; inspect + delete memories
- **Phase:** P9   **Status:** ENG   **Tags:** (T)

## Scope
tasks.md item: *"Cross-session adaptation; 👎 changes behavior; inspect + delete memories."* Plus
the P9 phase exit criterion (`dev-board/plan.md`): *"across two sessions assistant adapts to a
stated preference; a 👎 changes future behavior; user can inspect & delete what was learned."*

This is the phase-level integration verification pulling together every prior P9 task:
P9-01 (feedback capture), P9-02 (recall), P9-03 (learn/Celery), P9-04 (PII/GDPR gate), P9-05
(memory CRUD API), P9-06 (responder adaptation), P9-07 (guest Redis personalization + upgrade
migration), P9-08 (retention purge), P9-09 (frontend). Mirror how `P8-06-verify` /
`P7-05-verify` composed their phase-exit verification (read
`dev-board/code-review/P8-06-verify/task.md` + `engineer.md` for the expected shape/rigor) —
don't just re-run each prior task's own suite in isolation; prove the **whole chain**
end-to-end and report a clear yes/no on the P9 exit criterion.

Specifically verify (automated/composed integration tests preferred — "real stack, in-memory/
fake ports, no live HF/live Postgres" per the P4-10/P6-09/P7-05/P8-06 precedent; note plainly
anywhere a check genuinely needs live infra this environment lacks):

1. **Cross-session adaptation, end-to-end.** Simulate turn 1 for a logged-in user producing a
   learnable preference/fact (drive `run_learn_from_turn`/the Celery task body directly with
   fakes — not necessarily the broker), then drive a **second, separate** turn through the
   compiled graph (`app.agents.graph`, fake router/DB per the existing agent-test style) for the
   **same user** and confirm `memory_recall_node`/`recall()` surfaces what was learned, and the
   responder's assembled messages (P9-06) reflect it. Prove this is a genuine two-session round
   trip through real recall + real learn wiring, not two mocked pieces that were never actually
   connected.
2. **A 👎 changes future behavior.** Submit down-vote feedback (P9-01) for a turn, run the learn
   step (P9-03/04) and confirm: the memory associated with that turn is demoted/removed (not on
   a second identical pass — P9-03's idempotency fix must still hold), and/or an explicit
   "avoid X" preference is learned when a reason was given; then confirm a **subsequent** recall
   for that user no longer surfaces the demoted/removed memory (or does surface the new "avoid
   X" preference).
3. **Inspect + delete memories, end-to-end.** `GET /api/memory` (P9-05) reflects what P9-03
   actually wrote (not a hand-built fixture disconnected from the write path) for a user with
   real preferences + learned memories; `DELETE /api/memory/{id}` removes one and a subsequent
   `GET` no longer lists it; a **deleted** memory is also gone from what recall (P9-02) would
   return next turn (prove the CRUD delete and the recall read share the same underlying table/
   store, not two independent data paths that could drift).
4. **PII/GDPR gate holds under the full loop.** A turn containing a contact detail and/or an
   Art. 9 special-category statement, run through the *real* learn pipeline end-to-end, results
   in `user_memories` that are PII-redacted and never contain the special-category content —
   confirm via `GET /api/memory`'s response, not just P9-04's own unit tests in isolation.
5. **Guest → account upgrade carries personalization over** (P9-07): a guest accumulates
   session-only (Redis) personalization, upgrades, and the migrated result is visible via
   `GET /api/memory` post-upgrade (through the same PII/GDPR gate).
6. **Retention purge doesn't eat live users.** A quick sanity check that P9-08's "older than N
   days" query, exercised against a small fixture with both a stale and a fresh user, purges
   only the stale one — and that a freshly-active user (recent message via this same P9 loop)
   is correctly excluded.
7. **Frontend wiring sanity** (component-level, not full E2E): the memory panel's delete call
   and the message-feedback submit call hit exactly the endpoints the backend exposes (confirm
   against `frontend/lib/memory.ts` / `frontend/lib/messageFeedback.ts`, not just that the
   backend endpoints exist).
8. **Cross-task consistency check.** Grep for any place that duplicates the PII/GDPR gate, the
   "list a user's memories" query, or the confidence/dedup logic instead of reusing the P9-03/04
   primitives — flag any drift as a gap for the owning task, do not silently fix it here.

## Acceptance criteria
- [ ] All 8 points above are covered by automated tests (composed/integration-level where prior
      per-task tests only proved pieces in isolation) or a clearly documented reason something
      genuinely requires live infra this environment doesn't have.
- [ ] Full backend test suite green (`ruff check`, `ruff format --check`, `mypy`, `pytest`) —
      pre-check for P9-11, not a substitute for it, but don't leave it red here.
- [ ] Report states clearly: does the current P9 implementation meet the phase exit criterion?
      If a gap is found in any prior P9 task's work, flag it precisely (which task, what's
      missing) rather than silently patching around it, so the orchestrator can route a fix to
      the right task.

## Design references
- `dev-board/plan.md` — P9 exit criterion.
- `dev-board/app-design-and-features.md` §5.4 (teachable memory loop), §5.5 (feedback loop).
- Precedent: `dev-board/code-review/P8-06-verify/`, `dev-board/code-review/P7-05-verify/`,
  `dev-board/code-review/P6-09-manual-verify/`.
