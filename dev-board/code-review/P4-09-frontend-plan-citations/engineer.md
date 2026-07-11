# Engineer report — P4-09-frontend-plan-citations · Revision 2

## Summary
Consumed the two P4-07 wire additions in the frontend chat transport + UI:

1. The new SSE `plan` event (`{event:"plan", intent, steps[], workers[]}`) is now parsed by
   `chatStream.ts` and surfaced to `Chat.tsx`, which records it on the in-flight assistant message
   and renders a small "Planning: <intent> → running <workers>" strip (with the plan steps as a
   short list) — the visible planner/worker-step feedback the P4 exit criterion asks for.
2. `done.citations: SourceCitation[]` is now parsed (defensively) and rendered as a compact,
   inline "Sources" list under the finished answer, degrading per-field (linked title when a url
   exists, else snippet/source_id).

Both are strictly additive: a turn that ran no workers (`workers == []`, e.g. smalltalk) shows no
plan strip, and an answer with no citations shows no source list — existing turns render exactly as
before. Legacy `tool_call`/`tool_result` handling is untouched.

## Files changed
- `frontend/lib/chatStream.ts` — added `PlanEvent` + `SourceCitation` interfaces; added `plan` to
  the `ChatStreamEvent` union; extended `DoneEvent` with `citations`; added a `toChatEvent("plan", …)`
  case and `citations` parsing on the `done` case, plus defensive `nullableStr` / `strArray` /
  `parseCitations` helpers (mirror the existing `str(...)` tolerance — missing/non-array/malformed
  fields degrade to `[]`/`null` rather than throwing).
- `frontend/components/Chat.tsx` — added `plan?` and `citations` fields to `ChatMessageView` (+ a
  `TurnPlan` type); handled `case "plan"` and stored `citations` on `case "done"` in `handleEvent`;
  seeded `citations: []` on new user/assistant messages; rendered a new `PlanIndicator` (amber, reusing
  the tool-step visual language, only when `workers.length > 0`) and a `CitationList`/`CitationEntry`
  (only when non-empty) in `AssistantBubble`.
- `frontend/__tests__/chatStream.test.ts` — extended the "each event type" parse test with a `plan`
  frame and `done.citations: []`; added tests for plan default-empty arrays, full citation parsing,
  absent/partial (null-filled) citations, and a malformed non-array `citations` degrading to `[]`;
  updated the `streamChat` `done` expectation to include `citations: []`.
- `frontend/__tests__/Chat.test.tsx` — updated existing `done` events to carry `citations: []`
  (now required by `DoneEvent`); asserted the no-worker/no-citation turn shows no stray UI; added
  tests for the plan indicator rendering, no-worker plan suppression, citation-list rendering
  (linked title + snippet fallback), and no citation list when empty.

## Key decisions
- **Mirrored the existing `tool_call` end-to-end precedent** (schema type → `toChatEvent` case →
  union member → component handler → render) for `plan`, per the task's guidance, rather than inventing
  a new pattern. Citations follow the same defensive-parse convention already used for `finish_reason`.
- **`SourceCitation` fields are all `string | null`** to mirror the backend DTO exactly
  (`backend/app/schemas/chat.py::SourceCitation`, all `str | None`); `parseCitations` null-fills each
  field independently so a worker that emits only a url still renders (design §3 "cite sources").
- **Plan strip only renders when `workers.length > 0`; citation list only when non-empty** — keeps the
  change additive so smalltalk turns and no-source answers are visually unchanged (task non-goal:
  "no empty indicator boxes"). Reused the amber tool-step visual language for the plan strip to match
  the existing per-turn worker-step convention (design §3 "visible thinking/worker steps").
- **Did not touch the backend wire contract** (already landed in P4-07) — consume-only, per constraints.
- Kept the citation UI a simple inline list (no side panel/viewer), per the non-goal.

## How to verify
From `frontend/`:
- `npm run lint` — ESLint clean.
- `npm run type-check` — `tsc --noEmit`, no errors.
- `npm test` — jest, all suites green.
- Manual: a `job_search`-style turn shows the amber "🧭 Planning: <intent> → running <workers>" strip
  plus a "Sources" list under the answer; a plain chat turn shows neither.

## Tests (final step — mandatory)
- `npm run lint` → `✔ No ESLint warnings or errors`.
- `npm run type-check` → passed (no output/errors).
- `npm test` → `Test Suites: 6 passed, 6 total`, `Tests: 58 passed, 58 total`.
- No failures; no root-cause fixes needed. (The pre-existing `done`-event test expectations were
  updated because `DoneEvent` now legitimately carries `citations` — the contract changed, not a
  weakened assertion.)

## Self-check
- [x] Meets acceptance criteria (`plan` + `done.citations` parsed and surfaced; visible plan/worker
      step + citation list, both gracefully absent when empty; `tool_call`/`tool_result` unaffected;
      parser + component tests added for both, incl. malformed/missing tolerance; lint/tsc/test green).
- [x] No secrets committed; frontend transport (`lib/`) stays separate from the React component
      (`components/`) — mirrors the Router→Service split; no backend/wire-contract changes.
- [x] Tests/lints pass (output pasted above).

## Response to review (revision 2)

Code review (`code-review.md`) was CHANGES_REQUESTED with one major (C1) and one nit (C2);
architecture review was already APPROVED (no action). Both code-review findings are addressed.

- **C1 (major) — unvalidated `href` scheme is a DOM-XSS sink.** Added a `safeHttpUrl(url)` guard in
  `frontend/components/Chat.tsx`: it parses the citation url with `new URL(...)` in a try/catch and
  returns the url only when `.protocol` is `http:`/`https:`, otherwise `null`. `CitationEntry` now
  renders the `<a>` branch only when `safeHttpUrl` yields a value; any non-http(s) scheme
  (`javascript:`, `data:`, unparseable) degrades to the plain-`<span>` label branch — the label text
  is still shown as provenance but is never clickable. React's text nodes already escape the label, so
  the anchor `href` was the only unsafe sink (per the reviewer's own note). No CSP dependency: the
  scheme is filtered at render time.
  Added a component test in `frontend/__tests__/Chat.test.tsx`
  ("degrades an unsafe-scheme citation url to non-link text") that feeds a `javascript:`-scheme
  citation and asserts the label renders but no `link` role is present.
- **C2 (nit) — colliding citation `key`.** Changed the list key to
  `` `${citation.source_id ?? citation.url ?? "src"}-${i}` `` so two citations sharing a
  `source_id`/`url` (e.g. two chunks from one KB doc) no longer collide.

### Verification (revision 2, final step)
- `npm run lint` → `✔ No ESLint warnings or errors`.
- `npm run type-check` → `tsc --noEmit`, clean.
- `npm test` → `Test Suites: 6 passed, 6 total`, `Tests: 59 passed, 59 total` (+1: the new
  unsafe-scheme degradation test). No failures; no root-cause fixes needed.
