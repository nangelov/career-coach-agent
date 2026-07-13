---
name: project-parallel-worktree-failures
description: Shared working tree can hold uncommitted in-flight changes from parallel tasks; don't fix another task's red tests
metadata:
  type: project
---

The single working tree may contain **uncommitted changes from parallel in-flight tasks**
(e.g. while doing P6-02 schema, the tree also had P6-01 taxonomy + P6-03 tavily edits to
`internet_search.py`/`test_tools.py`). `git status` at session start can say "clean" but be
a stale snapshot.

**Why:** the multi-agent pipeline runs sibling P6-xx tasks concurrently against one repo.

**How to apply:** when the full suite has failures, `git status --short` to see what's yours.
Triage/fix only failures in files **your task touches**; a red test in an unrelated module
(another task's territory) is pre-existing — flag it in `engineer.md` as out-of-scope, do
**not** edit that module to make it green. Confirm your own scope is fully green before handoff.
