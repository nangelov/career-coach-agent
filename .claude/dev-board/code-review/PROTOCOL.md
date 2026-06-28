# Agent handoff — see the skill

The handoff protocol now lives in the **`agent-handoff` skill**, loaded by the main (orchestrator) agent:

- `.claude/skills/agent-handoff/SKILL.md`

That skill is the single source of truth for the folder layout, the
engineer → code-reviewer → system-architect pipeline, the per-file templates, and the verdict gates.
This `code-review/` folder holds the runtime artifacts (`queue.md` and one `<task-id>/` folder per task).

Subagents (`fullstack-engineer`, `code-reviewer`, `system-architect`) are defined in `.claude/agents/` and
each reads the skill for its file contract on dispatch.
