# Engineer report — P10-04-repl-removal-confirm · Revision 1

## Summary
Confirmation + regression-guard task. Verified that v1's `run_python_code` REPL (and any
arbitrary-code-execution surface) is **absent** from `backend/app/`, and added a regression test
that locks this in so a future PR cannot silently reintroduce a REPL/eval tool. No sandboxed
evaluator was built — nothing in the current tool set needs bounded math (YAGNI, per task
constraint).

## Confirmation (acceptance criterion 1)
Grepped the whole `backend/app/` tree for code-execution surfaces
(`exec(`, `eval(`, `subprocess`, `os.system`, `__import__`, `PythonREPL`, `run_python`,
`pty.spawn`, `popen`): **none found.** The only matches for `eval`/`exec`/`compile` are legitimate
and unrelated — `re.compile(...)` (regex), `builder.compile()` (LangGraph graph build),
`registry.execute(...)`, and the substring "empty"/"complete". v1's tool code lives only under
`legacy-code/` (moved in P0-12); the v2 tool set was rebuilt from scratch.

The complete LLM-callable tool surface (verified exhaustively):
- Default chat registry (`app/tools/registry.py`): `current_date_and_time`, `internet_search`.
- Per-turn dashboard bundle (`app/tools/dashboard.py`, registered by the dashboard node):
  `read_dashboard`, `propose_goal`, `propose_milestone`, `propose_task`, `log_progress`.

None exposes arbitrary code execution. (Planner / market-signal extraction are internal LLM calls,
not registered native tools.)

## Files changed
- `backend/tests/test_no_code_exec_tool.py` — new regression test (only change in this task).

## Key decisions
- **No new production code.** Per task constraints + design §7, this is a confirmation task; adding
  a sandboxed evaluator "just in case" would violate YAGNI. Confirmed no current tool needs bounded
  math before deciding not to build one.
- **Three complementary asserts** (design §7 "Tool isolation"):
  1. `test_registered_tool_set_is_exactly_the_known_good_set` — asserts the exact known-good tool
     name set across *both* registries, so any newly added tool forces a conscious update at the
     one place a reintroduced REPL would have to be noticed.
  2. `test_no_registered_tool_exposes_code_execution` — denylist on every tool's name +
     description (python/repl/exec/eval/shell/interpreter…).
  3. `test_no_code_execution_surface_in_backend_app` — scans the whole `backend/app` tree for
     code-exec builtins. A REPL tool cannot exist without one of these, so this is the durable
     guarantee; word-boundary + literal-paren patterns deliberately exclude legitimate
     `re.compile`, `.execute()`, `.compile()`.

## How to verify
```bash
cd backend && source .venv/bin/activate
ruff check tests/test_no_code_exec_tool.py
ruff format --check tests/test_no_code_exec_tool.py
mypy tests/test_no_code_exec_tool.py
python -m pytest tests/test_no_code_exec_tool.py -q
```

## Tests (final step — mandatory)
- `ruff check` / `ruff format --check` / `mypy` on the new file: **all pass** (no issues).
- New test file: `3 passed in 0.69s`.
- Full backend suite: `python -m pytest -q` → **902 passed, 83 skipped** in 5.27s. The 83 skips are
  the live-DB / heavy-dep tests skipped in this environment (project convention), not failures.
- No failures — no root-cause fixes needed.

## Self-check
- [x] Meets acceptance criteria (documented confirmation + registered-tool denylist test; no
      evaluator added since none needed).
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (test-only change).
- [x] Tests/lints pass (results pasted above).
