# Task P4-09-frontend-plan-citations — Stream planner/worker steps + citations to the UI

- **Phase:** P4   **Status:** ENG   **Tags:** (F)

## Scope

From `dev-board/tasks.md` P4:
> **(F)** Stream planner/worker steps to the UI.

The backend (P4-07) now drives `POST /api/chat` through the multi-agent graph and extended the SSE
`ChatEvent` wire contract with two new pieces the frontend does not yet consume:

- A new `plan` event (`backend/app/schemas/chat.py::PlanEvent`), emitted once right after `start` and before
  the first `token`: `{event: "plan", intent: string, steps: string[], workers: string[]}` — the classified
  intent, the human-readable decomposition, and which worker nodes ran this turn.
- `done` now carries `citations: SourceCitation[]` (was always `[]` before):
  `{source_id, title, url, snippet, worker}` (all fields optional/nullable) — the grounding sources backing
  the answer.

This task updates the frontend transport + chat UI (`frontend/lib/chatStream.ts`,
`frontend/components/Chat.tsx`, from P1-08) to parse and render both, giving the user visible "the assistant
is planning / running X worker" feedback and a citation list on the finished answer — the UI half of the P4
exit criterion *"routes planner → ≥1 worker → responder; streams; shows citations."*

## What already exists — reuse, don't reinvent

- `frontend/lib/chatStream.ts` — the SSE parser/transport (`createSSEParser`, `toChatEvent`, `streamChat`).
  `ChatStreamEvent` is the discriminated union the component consumes; `tool_call`/`tool_result` are already
  precedent for adding a new discriminated event variant end-to-end (schema type → `toChatEvent` case → union
  member). Follow that exact pattern for `plan`, and extend `DoneEvent`'s type + `toChatEvent("done", ...)`
  case with `citations`.
- `frontend/components/Chat.tsx` — `ChatMessageView`/`ToolStep`/`ToolStepIndicator` and the `handleEvent`
  switch are the existing precedent for rendering per-turn worker-step UI (`tool_call`→"calling", `tool_result`
  →"done"). Add a `plan` case that records intent/steps/workers onto the in-flight assistant message (new
  fields on `ChatMessageView`, e.g. `plan?: { intent: string; steps: string[]; workers: string[] }`) and
  render it above/alongside the existing tool-step indicators — a small "Planning: <intent> → running
  <workers.join(', ')>" strip is sufficient; steps can be a short list. Add a `citations` field to
  `ChatMessageView`, populated from the `done` event, rendered as a compact source list under the finished
  answer (title/url as a link when present, otherwise the snippet/source_id — degrade gracefully since every
  field is optional).
- `frontend/__tests__/chatStream.test.ts` / `frontend/__tests__/Chat.test.tsx` — existing test patterns for
  the parser and component; extend them for the two new pieces rather than writing a parallel test file.

## Implementation approach

- `chatStream.ts`: add a `PlanEvent` interface, a matching `toChatEvent("plan", ...)` case, add it to the
  `ChatStreamEvent` union; extend `DoneEvent` with `citations: SourceCitation[]` (new `SourceCitation`
  interface mirroring the backend DTO — all fields `string | null`) and parse it out of the `done` frame's
  `data.citations` (default to `[]`, tolerate a missing/malformed field defensively — mirror how existing
  fields use `str(...)`/nullish coalescing rather than assuming well-formed input).
- `Chat.tsx`: handle `case "plan"` in `handleEvent` (store intent/steps/workers on the in-flight assistant
  message); handle the `citations` field on the `done` case (store on the message). Render:
  - A lightweight "plan" indicator (reuse the existing amber tool-step visual language or a similarly small,
    unobtrusive element) shown while/after the turn is in flight — this is the "visible worker steps" ask.
  - A citations list under the completed assistant answer (only when non-empty) — small, unobtrusive, doesn't
    have to be fancy (a list of linked titles/snippets is enough for this task).
- Keep this additive: turns that ran no workers (`plan.workers == []`, e.g. smalltalk) and/or have no
  citations should render exactly as they do today (no empty indicator boxes).
- Update/extend the existing frontend tests (`chatStream.test.ts` for the parser, `Chat.test.tsx` for
  rendering) to cover: a `plan` event is parsed/rendered, `done.citations` is parsed/rendered, and the
  no-worker/no-citation case renders unchanged.

## Acceptance criteria

- [ ] `plan` events are parsed by `chatStream.ts` and surfaced to the component.
- [ ] `done.citations` is parsed by `chatStream.ts` and surfaced to the component.
- [ ] `Chat.tsx` visibly renders the planner/worker step info while a turn is in flight (or once known) and a
      citation list on the finished answer, both gracefully absent when empty.
- [ ] Existing `tool_call`/`tool_result` handling is unaffected (still rendered exactly as before — the wire
      union keeps them as a superset per P4-07).
- [ ] Unit tests updated/added for the parser (`plan` event shape, `done.citations` parsing, malformed/missing
      field tolerance) and the component (plan indicator renders, citations render, both absent → no stray
      UI).
- [ ] `npm run lint` / `tsc` / `npm test` (or the project's equivalent commands) all green.

## Design references

- `dev-board/app-design-and-features.md` §3 — "visible thinking/worker steps", Response Agent "cite sources".
- `dev-board/app-design-and-features.md` §9 — API surface.
- `dev-board/code-review/P4-07-chat-graph-integration/` — the backend `PlanEvent`/`DoneEvent.citations` wire
  contract this task consumes (read `engineer.md` there for the exact shapes/rationale).
- `dev-board/code-review/P1-08-frontend-chat/` — the existing chat page/transport this task extends.

## Constraints / non-goals

- Do NOT change the backend wire contract — it's already landed (P4-07); this task only consumes it.
- Do NOT redesign the chat UI wholesale — extend the existing component/transport in place, matching its
  current visual language (Tailwind utility classes, existing color/status conventions).
- Do NOT build a rich citation viewer/side panel — a simple inline list is sufficient for this task.
