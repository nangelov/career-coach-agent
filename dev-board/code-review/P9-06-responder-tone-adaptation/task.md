# Task P9-06-responder-tone-adaptation — responder adapts to recalled preferences/memories
- **Phase:** P9   **Status:** ENG   **Tags:** (B)

## Scope
Make the Response Agent actually **use** `AgentState.memory` (populated by P9-02's recall step)
to adapt tone/depth/style, instead of leaving it recalled-but-unused.

From `dev-board/tasks.md` (P9):
> Responder adapts tone/depth to recalled preferences.

### What already exists (read before building)
- `backend/app/agents/responder.py::Responder._build_messages` — assembles the synthesis
  prompt: persona (`RESPONDER_SYSTEM_PROMPT`) → optional job-hunting redirect note → grounding
  block (`_grounding_block`, fenced untrusted worker content) → history → current user turn.
  **`state.memory` is never read here today** — that's this task's gap to close.
- `backend/app/agents/state.py::MemoryContext` — `preferences: dict[str, Any]` (explicit,
  authoritative — tone/formality/language/focus-areas/do-don't-list per §5.4) and
  `memories: list[str]` (top-k recalled learned-fact strings).
- `backend/app/agents/memory_agent.py` (P9-02) — populates `state.memory` before the planner
  runs; by the time the responder node runs, `state.memory` already carries whatever recall
  found (empty for guests / users with nothing learned yet).
- `_grounding_block`'s fencing pattern (`fence_untrusted`, `app.guardrails`/similar helper) — a
  good model for how to inject **another** system-turn block safely, though note: unlike worker
  content, `preferences`/`memories` are **first-party, user-controlled data** (the user set
  their own prefs; memories were extracted from their own turns and already passed the P9-04
  GDPR/PII gates before being written) — they do **not** need the "untrusted, do not follow
  instructions" fencing treatment worker/crawled content gets. Treat them as trusted persona
  context, not untrusted grounding.

## Acceptance criteria
- [ ] `_build_messages` (or an equivalent seam) injects a personalization system-turn block when
      `state.memory.preferences` and/or `state.memory.memories` is non-empty — e.g. "The user has
      told you: tone=concise, focus=fintech PM roles. You've previously learned: 'prefers bullet
      points', 'based in Berlin'. Adapt your tone, depth, and advice accordingly without
      explicitly repeating this back verbatim unless relevant." (exact wording is the engineer's
      call — keep it short, since this competes for context budget with grounding + history).
- [ ] Both `preferences` (explicit — authoritative) and `memories` (inferred) are represented,
      and it's clear in the prompt that **explicit preferences take precedence** over an inferred
      memory if they ever conflict (§5.4 point 4 "explicit edits override inferred memories" —
      this is the natural place that plays out at generation time, complementing P9-05's
      CRUD-level "explicit edit overrides" already confirmed there).
- [ ] When `state.memory` is empty (guest, or a user with nothing recalled yet) the prompt is
      **unchanged** from today — no empty block, no behavior change, no regression to the P1/P4
      walking-skeleton persona.
- [ ] Applies on **both** paths: buffered `synthesize()` and the streaming `stream()` — both
      already call the same `_build_messages`, so a single change point should cover both; verify
      with a test on each.
- [ ] Unit tests: no memory → prompt identical to before; preferences only; memories only; both;
      a case asserting explicit preference wording is distinguishable from inferred-memory
      wording in the assembled messages (so a reviewer/future engineer can confirm precedence
      framing exists, not just "trust the model").

## Design references
- dev-board/app-design-and-features.md: §5.4 "Personalization — the teachable agent", the
  "Respond adapted to that context" loop step and point 4 (explicit overrides inferred).
- `backend/app/agents/responder.py`, `backend/app/agents/state.py`.

## Constraints / non-goals
- No change to recall (P9-02), learn (P9-03/04), or the CRUD API (P9-05).
- No new LLM call — this is a prompt-assembly change only, still one synthesis call per turn.
- No frontend changes.
