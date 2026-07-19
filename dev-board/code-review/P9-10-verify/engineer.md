# Engineer report — P9-10-verify · Revision 1

## Summary
P9 phase-exit verification: a single composed, integration-level suite
(`tests/test_p9_exit_verification.py`, 8 tests) that drives the whole teachable-memory /
feedback chain end-to-end over the **same** durable tables — proving the `plan.md` P9 exit
criterion rather than re-running each prior task's isolated pieces. **Verification-only: no
product code was changed.** Points 1–6 run against **live Postgres** (the `vector(4096)` + FK
schema SQLite can't represent), faking only the true external edges (the 8B embedder → a fixed
4096-dim vector; the extractor LLM → a scripted candidate list); they skip cleanly when Postgres
is unreachable, exactly like the sibling `*_persistence` suites. Points 7–8 are pure source scans
that always run.

**Verdict on the P9 exit criterion: MET.** Across two sessions the assistant adapts to a stated
preference; a 👎 changes future behaviour; the user can inspect and delete what was learned — all
proven over shared `user_memories` / `preferences` rows. No gap found in any prior P9 task.

## Files changed
- `backend/tests/test_p9_exit_verification.py` — the P9-10 phase-exit suite (8 tests, one per
  task point). New file (present from the prior session; this pass fixed its typing and finalized
  the gate — see below).
- 17 sibling P9 files reformatted by `ruff format` (formatting only, zero logic change) — see
  "Key decisions" / the flag below.

## Key decisions
- **mypy root-cause fix (not a `# type: ignore`).** The `planner` test seam `_planner_chat()` was
  typed `Callable[[AgentState], dict[str, object]]`, which mypy rejects against `stream_graph`'s
  `planner: PlannerNode` (`= StateNode[AgentState, Any]`, `app/agents/graph.py:125`). Fixed by
  importing and using the module's own `PlannerNode` / `NodeUpdate` aliases — the exact idiom the
  sibling agent suites already use (`tests/test_agent_graph.py`, `tests/test_input_guardrails.py`).
  No `type: ignore`, matches the real node contract.
- **Live-Postgres posture (design §5.4/§5.5).** The point of P9 is that learn (write), recall
  (read) and CRUD (delete) address the *same* rows; proving that with fakes would prove a shared
  dict, not a shared table — so 1–6 use the real stores against live Postgres, per the
  `*_persistence` precedent, not the fully-offline P8-06 style.
- **Cross-task consistency (point 8) confirmed clean.** The PII/Art. 9 gate, the "list a user's
  memories" query, and the dedup/confidence logic each live in exactly one place and are reused
  (guest personalization imports `app.memory.learn`'s gate rather than re-implementing it) — the
  assertion holds, so no drift to flag back to an owning task.

## How to verify
- Whole gate: `cd backend && make check` (runs check-deps → ruff check → ruff format --check →
  mypy → pytest; integration suites skip without a DB).
- Live-DB run of this module: bring up Postgres + migrate, then
  `make test-integration` (or the all-in-one `make test-integration-full`).
- This module alone against live PG:
  `test-integration`-style env + `uv run --no-sync pytest tests/test_p9_exit_verification.py -v`.

## Tests (final step — mandatory)
- `uv run --no-sync ruff check .` → **All checks passed!**
- `uv run --no-sync ruff format --check .` → **266 files already formatted** (green; see flag).
- `uv run --no-sync mypy app/ migrations/` → **Success: no issues found in 158 source files**.
- `uv run --no-sync mypy tests/test_p9_exit_verification.py` → **Success: no issues found**.
- `make test-integration-full` (live docker-compose Postgres, migrated) →
  **959 passed, 1 skipped in 23.32s**. The 1 skip is a pre-existing environment-gated test,
  not in this module.
- This module against live Postgres, verbose → **8 passed** (all 8 task points ran, none skipped):
  cross-session adaptation, 👎 changes behaviour, inspect+delete, PII/GDPR gate, guest upgrade,
  retention spares fresh users, frontend wiring, cross-task consistency.

### Flag: ruff-0.15.20 format drift on sibling P9 files (disclosed, not silent)
The whole P9 phase is still uncommitted in the working tree. `ruff format --check .` (pinned
ruff 0.15.20 in `uv.lock`, the version CI runs) reported 17 of those uncommitted P9 files as
needing reformat — pure signature-line collapse (net whitespace/wrapping only; verified no
non-formatting hunks). Since the P9-10 exit criterion requires a green gate as the pre-check for
P9-11, I ran `ruff format .` (formatting only, no logic touched): `app/agents/memory_agent.py`,
`app/agents/responder.py`, `app/memory/{guest_personalization,learn,store}.py`,
`app/services/{chat,guest_memory,guest_upgrade,memory}.py`, `app/tasks/retention_purge.py`, and
6 test modules. Flagging here for transparency — this was formatting drift in prior P9 tasks'
uncommitted work, not a logic change by P9-10.

## Self-check
- [x] Meets acceptance criteria — all 8 points covered by automated tests; full gate green;
      report states the exit criterion is MET and flags the (formatting-only) drift.
- [x] No secrets committed; verification-only, no Router→Service→Agent/Repo layering touched.
- [x] Tests/lints pass (results pasted above).
