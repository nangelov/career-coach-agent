---
name: ruling-langmem-handrolled-exclusion
description: langmem stays out of the CI curated-install list because P9 hand-rolled memory extraction on the langgraph BaseStore seam instead of using LangMem
metadata:
  type: project
---

P9 (teachable memory) does **not** import `langmem`/`trustcall` anywhere in `app/` or `tests/`.
Memory extraction was hand-rolled in `app/memory/learn.py`, and `app/memory/store.py` conforms
to `langgraph.store.base.BaseStore` (langgraph is already curated). Verified by grep in P9-11.

**Why:** CLAUDE.md's locked decision names LangMem for teachable memory, but P9-02..P9-10
deliberately built on the langgraph store seam instead — a blessed deviation in those tasks.
`langmem` is therefore correctly kept in `INTENTIONAL_EXCLUSIONS` (reason "declared but not yet
imported") in `scripts/check_curated_deps.py` and out of the CI/Makefile `uv pip install` list.
Adding it would waste the free CI tier for an unused dependency.

**How to apply:** Do NOT flag langmem's absence from the curated CI list as a gap — it is correct
as long as grep shows no `langmem`/`trustcall` imports in `app/`. Open follow-up (not a blocker):
if the hand-rolled path is final, the `pyproject.toml` langmem dep + the "not yet imported"
exclusion reason should eventually be reconciled to intentional-permanent (or the dep dropped).
Related: [[ruling-curated-ci-light-deps]], [[pattern-p1-walking-skeleton]].
