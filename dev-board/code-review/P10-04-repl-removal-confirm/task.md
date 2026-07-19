# Task P10-04-repl-removal-confirm — confirm v1 `run_python_code` REPL is removed

- **Phase:** P10   **Status:** ENG   **Tags:** (B)

## Scope
Design §7: "the v1 `run_python_code` REPL is **removed** (it was an arbitrary-code-execution
risk and only did calculations). If math is needed, use a sandboxed/limited evaluator."

This is expected to already be true (v1 code was moved to `legacy-code/` in P0-12 and the v2
tool set was rebuilt from scratch in P1-03 with only `current_date_and_time` /
`internet_search`, later joined by dashboard/market/RAG tools in P4–P8 — none of which are a
code-exec tool). This task is a **confirmation + guardrail pass**, not a rewrite:

1. Grep the entire `backend/app/` tree (agents, tools, guardrails, api) for any code-execution
   surface: `exec(`, `eval(`, `subprocess`, a REPL tool, a "python" tool registration, etc.
   Confirm none of the native tools registered in the LangGraph tool set expose arbitrary code
   execution.
2. If a legitimate need for *bounded* math exists anywhere in the current tool set (it should
   not, per design — check before assuming), scope a sandboxed/limited evaluator (e.g. a safe
   expression evaluator restricted to arithmetic, no imports/attribute access/builtins) rather
   than `eval`. Only build this if you find an actual current need — do not add a tool that
   doesn't exist yet "just in case" (YAGNI).
3. Write a short confirmation note + a regression test that asserts no code-exec tool is present
   in the registered tool list (so a future PR can't silently reintroduce one).

## Acceptance criteria
- [ ] Documented confirmation (in `engineer.md`) that no `run_python_code`-equivalent exists in
      `backend/app/` outside `legacy-code/`.
- [ ] A test asserting the registered tool set contains no code-execution tool (e.g. checks tool
      names/descriptions against a denylist, or asserts the known-good tool list exactly).
- [ ] If a sandboxed evaluator was genuinely needed and added: it has no `eval`/`exec`, no
      import/attribute access, and is unit-tested against both valid expressions and injection
      attempts (e.g. `__import__('os').system(...)`).
- [ ] `ruff`, `ruff format --check`, `mypy`, `pytest` all green.

## Design references
- dev-board/app-design-and-features.md §7 ("Tool isolation" bullet)
- CLAUDE.md — "v1's `run_python_code` REPL is removed in v2 (ACE risk)."

## Constraints / non-goals
- Do not build a sandboxed evaluator speculatively if nothing in the current codebase needs it —
  a confirmation + regression test may be the entire task.
