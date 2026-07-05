---
name: agent-handoff
description: Orchestration playbook for the fullstack-engineer → (code-reviewer + system-architect in parallel) subagent pipeline via file-based handoff in dev-board/code-review/. Load this when an orchestrator agent drives [IMPLEMENTATION <task>], [IMPLEMENTATION_NEXT_TASK], or [CODE_REVIEW <scope>] triggers, or whenever subagents must communicate through findings on disk rather than prose.
---

# Agent Handoff — orchestration playbook

The **orchestrator agent** coordinates three worker subagents. All agents communicate **only through files in
`dev-board/code-review/`** — never by relaying findings as prose.

Subagents (custom agent types, dispatched with the Agent tool):
- **fullstack-engineer** — Senior full-stack engineer; implements one task.
- **code-reviewer** — Senior code reviewer; reviews correctness/security/quality.
- **system-architect** — Reviews the work against `dev-board/plan.md` + `dev-board/app-design-and-features.md`.

**The code-reviewer and system-architect always run in parallel** (dispatched together in one message), never
one-after-the-other.

## Triggers (how the user starts work)

| Trigger | Meaning | Flow |
|---------|---------|------|
| `[IMPLEMENTATION <task>]` | Implement a specific task (id from `dev-board/tasks.md`, or a described task) | Implementation pipeline |
| `[IMPLEMENTATION_NEXT_TASK]` | Pick the next unchecked item in `dev-board/tasks.md` and implement it | Implementation pipeline |
| `[CODE_REVIEW <full_codebase>]` | Review the whole codebase | Review-only flow (no engineer step) |
| `[CODE_REVIEW <given area>]` | Review a path/module/area | Review-only flow, scoped to that area |

- For `[IMPLEMENTATION_NEXT_TASK]`, the next task = first unchecked `[ ]` item in `dev-board/tasks.md`, in
  document order, skipping `(D)` decision items — if the next item is a `(D)` decision, surface it to the user
  instead of dispatching the engineer.
- For `[CODE_REVIEW ...]`, there is no engineer step first; open a review folder
  `dev-board/code-review/CR-<seq>-<slug>/` with a `task.md` describing the scope, then run the parallel review.
  If findings require fixes, route to the engineer and re-verify (same loop).

## Why file-based
Durable, auditable trail; each agent starts from structured input, not a paraphrase; the orchestrator stays
thin — it routes by reading verdicts, it does not carry content between agents.

## Folder layout

```
dev-board/
├── tasks.md                         # actionable task list (orchestrator picks from here)
├── plan.md                          # phased execution plan
├── app-design-and-features.md       # system design reference
└── code-review/
    ├── queue.md                     # the board: every task + its current status
    └── <task-id>/                   # one folder per task, e.g. P1-01-llm-client
        ├── task.md                  # orchestrator: the assignment (scope, acceptance, refs)
        ├── engineer.md              # fullstack-engineer: what was built + how to verify
        ├── code-review.md           # code-reviewer: findings + verdict
        └── architecture-review.md  # system-architect: design-conformance findings + verdict
```

`<task-id>` convention: `<phase>-<seq>-<slug>` (e.g. `P0-03-config`, `P4-02-planner`), matching `dev-board/tasks.md`.

## The pipeline (MUST always follow these steps)

```
orchestrator → fullstack-engineer ──▶ ┌─ code-reviewer ─┐ (PARALLEL) ──▶ both APPROVED? ──▶ DONE
                      ▲                └─ system-architect┘                     │
                      │                                                         │ either CHANGES_REQUESTED
                      └──────────────── fix loop ───────────────────────────────┘
                       (engineer fixes → only the reviewer(s) that flagged issues re-verify)
```

1. **Orchestrator** writes `dev-board/code-review/<task-id>/task.md`, sets the `queue.md` row to `ENG`,
   dispatches the engineer with just the task id + "read the agent-handoff skill / your task.md".
2. **fullstack-engineer** implements. **Final step before writing the report:** run the test suite; if any
   test fails, fix the **root cause** — whether the defect is in the implementation or in the test itself —
   and re-run until green. Never hand off to review with known-failing tests. Then writes
   `<task-id>/engineer.md` (including the test results). Orchestrator sets status `REVIEW`.
3. **code-reviewer AND system-architect run in parallel** — dispatch both in a single message. Each reads the
   diff + `engineer.md` and writes its own file (`code-review.md` / `architecture-review.md`) ending in a
   `Verdict:` line. Wait for both to finish.
4. **Route on the two verdicts:**
   - **Both `APPROVED`** → task is **DONE**: set `queue.md` to `DONE` and **check the item off in
     `dev-board/tasks.md`** (`[ ]` → `[x]`).
   - **Either (or both) `CHANGES_REQUESTED`** → status `ENG`; re-dispatch the engineer, which reads **every**
     review file with findings, fixes them, **re-runs the test suite as the final step and fixes the root
     cause of any failures (code or test) before reporting**, appends a `Response to review` section, and
     bumps the revision in `engineer.md`.
5. **Re-verify after a fix:** dispatch **only the reviewer(s) that requested changes** to re-check the new
   revision (in parallel if both did). The reviewer(s) that already `APPROVED` are not re-run unless the fix
   touched their concern — if the engineer's changes are broad, re-run both. Loop back to step 4.

A task is **DONE only when both `code-review.md` and `architecture-review.md` show `APPROVED`** for the **same
(latest) engineer revision**. The orchestrator never skips a reviewer and never declares done on one verdict.

## Orchestrator responsibilities
- Recognize the triggers above; pick the task from `dev-board/tasks.md` accordingly. Keep each task small
  (one item); split if the engineer flags it too big.
- Maintain `dev-board/code-review/queue.md` (create it from the template below if missing).
- **Engineer is dispatched alone; the two reviewers are dispatched together (parallel).** Route on the
  `Verdict:` lines, never on your own judgment of the work.
- Never relay findings yourself — point the next agent at the files. Only summarize status to the user.
- On `CHANGES_REQUESTED`, re-dispatch the engineer; do not argue the finding for them.
- **On completion, check the task off in `dev-board/tasks.md`** (`[ ]` → `[x]`) and set `queue.md` to `DONE`
  — only when both reviews are `APPROVED` for the same revision.

### `queue.md` template
```markdown
# Review queue

| task-id | title | phase | status | rev | code-review | arch-review |
|---------|-------|-------|--------|-----|-------------|-------------|
| P0-01-scaffold | backend skeleton | P0 | REVIEW | 1 | pending | pending |
```
- **status:** `ENG` (engineer working) · `REVIEW` (both reviewers running in parallel) · `DONE` · `BLOCKED`.
- **rev:** current engineer revision number.
- **code-review / arch-review:** `pending` · `APPROVED` · `CHANGES_REQUESTED` (the latest verdict of each).

## File templates

### `task.md` (orchestrator)
```markdown
# Task <task-id> — <short title>
- **Phase:** <Px>   **Status:** ENG|REVIEW|DONE|BLOCKED   **Tags:** (B)/(F)/(I)
## Scope
<one tasks.md item, kept small>
## Acceptance criteria
- [ ] <testable outcome>
## Design references
- dev-board/plan.md: <phase/section>   ·   dev-board/app-design-and-features.md: <§>
## Constraints / non-goals
<out of scope>
```

### `engineer.md` (fullstack-engineer)
```markdown
# Engineer report — <task-id> · Revision <n>
## Summary
## Files changed
- `path` — why
## Key decisions
- decision + rationale (tie to design refs)
## How to verify
- commands / steps
## Tests (final step — mandatory)
- Command(s) run + result (paste output/summary)
- If any test failed: root cause (code bug vs. test bug) + the fix applied. Do not report DONE with red tests.
## Self-check
- [ ] Meets acceptance criteria
- [ ] No secrets committed; Router→Service→Agent/Repo layering respected
- [ ] Tests/lints pass (paste result)
## Response to review (revisions only)
- <finding id> → how addressed
```

### `code-review.md` (code-reviewer)
```markdown
# Code review — <task-id> · engineer revision <n>
## Verdict: APPROVED | CHANGES_REQUESTED
## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | blocker/major/minor/nit | ... | ... | ... |
## Notes
```

### `architecture-review.md` (system-architect)
```markdown
# Architecture review — <task-id> · engineer revision <n>
## Verdict: APPROVED | CHANGES_REQUESTED
## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | ... | ... | ... |
## Cross-cutting checks
- [ ] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [ ] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only; in-process embeddings)
- [ ] Interfaces-before-implementations (LLMClient, DocumentParser, repositories, guardrails)
- [ ] Budget posture respected (free/OSS/self-hosted)
## Notes
```

## Verdict → gate
- **blocker / major** in either review ⇒ `CHANGES_REQUESTED`.
- **minor / nit** ⇒ may be `APPROVED` with notes; engineer addresses or explicitly defers next revision.

## Rules for every agent
- Read inputs from disk; don't rely on prose beyond the task id + this skill pointer.
- Always end a review file with an explicit `Verdict:` line — routing depends on it.
- Never edit another agent's section; append your own file or your own revision/`Response` block.
