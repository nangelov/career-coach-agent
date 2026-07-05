---
name: project-dev-board-path
description: dev-board/ and code-review task folders live at the REPO ROOT, not under backend/
metadata:
  type: project
---

The `dev-board/` tree (`plan.md`, `app-design-and-features.md`, `tasks.md`,
`code-review/<task-id>/`) lives at the **repository root**
(`/home/.../career-coach-agent/dev-board/`), NOT under the `backend/` cwd the agent
is dispatched in. The `.claude/skills/` and `.claude/agents/` dirs are also at repo
root. Only `.claude/agent-memory/` is under `backend/`.

**Why:** dispatch cwd is `backend/`, but task briefs/design docs and the SKILL.md
are one level up.
**How to apply:** read task.md / engineer.md / SKILL.md with absolute repo-root
paths (`../dev-board/...`), and write `engineer.md` to the repo-root code-review
folder — not a backend-relative path.
