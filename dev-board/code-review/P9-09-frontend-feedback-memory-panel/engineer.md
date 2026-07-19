# Engineer report — P9-09-frontend-feedback-memory-panel · Revision 1

## Summary
Built the whole P9 personalization/feedback frontend surface consuming the existing P9-01/P9-05
backend APIs (no new backend surface):
- Per-message 👍/👎 (+ optional one-line reason on 👎) on completed assistant turns, with an inline
  "Try again?" affordance that re-runs the same user turn through the existing streaming path.
- A `/memory` page — "What the coach knows about you" — with editable explicit preferences and a
  view/delete list of learned memories, plus a guest sign-in state.

## Files changed
- `frontend/lib/messageFeedback.ts` (new) — client for `POST /api/messages/{id}/feedback`
  (`submitMessageFeedback`); wire type mirrors `MessageFeedbackResponse`; typed
  `MessageFeedbackApiError`; injectable `fetchImpl`/`baseUrl`; reason omitted when blank.
- `frontend/lib/memory.ts` (new) — client for the `/api/memory` surface (`getMemory`,
  `updatePreferences`, `deleteMemory`, `deleteAllMemories`); wire types mirror `MemoryView`/
  `Preferences`/`LearnedMemory` verbatim; typed `MemoryApiError`; defensive parsing.
- `frontend/components/MemoryPanel.tsx` (new) — preferences form (tone/formality/language/focus/
  avoid) + learned-memory list with immediate per-item Delete (optimistic, rollback on failure);
  guest state short-circuits the API; loading/load-error/save/delete states.
- `frontend/app/memory/page.tsx` (new) — auth-gated page shell mirroring `app/profile/page.tsx`
  (session hydrated via BFF `fetchSession()`, Login when unauthenticated).
- `frontend/components/Chat.tsx` — `ChatMessageView` now carries `messageId` (stamped from
  `start`/`done`/`cancelled`); `Memory` header nav link; `handleSend` refactored into a shared
  `sendMessage(text)` reused by "Try again?"; `MessageFeedbackControls` rendered on completed,
  id-stamped assistant turns.
- Tests: `frontend/__tests__/messageFeedback.test.ts`, `memory.test.ts`, `MemoryPanel.test.tsx`
  (new); `Chat.test.tsx` extended with feedback/try-again cases.

## Key decisions
- **Reused the catch-all BFF proxy** (`app/api/[...path]/route.ts`, which exports GET/POST/PUT/
  DELETE/PATCH) — the four new endpoints route through it with server-side `Authorization`
  injection (SEC-04 / §7.2), so no new BFF route handlers were added.
- **message_id capture from `done`/`cancelled`** (also `start` for early stamping) per task; feedback
  controls gate on `status === "done" && messageId` so a still-streaming or id-less turn shows none.
  Guardrail/off-topic/error turns that emit a `done` with an id get the same controls.
- **Try again = re-send** (§5.5): no new "regenerate" backend endpoint. `sendMessage` re-streams the
  prior user turn via the existing path (appends a fresh turn), which the task explicitly accepts.
  Note: this produces a new turn rather than replacing the down-voted one — acceptable per the task.
- **Idempotent-upsert reflection** (P9-01): the widget stores the last confirmed `rating` and sets
  `aria-pressed`; a 👎 submits immediately then reveals the optional reason input (re-submit updates
  the same row). No modal (§5.5 "a simple inline text input is enough").
- **Memory panel: no approve/reject, no per-fact confirmation** (§6.10) — edits and deletes are
  immediate; delete is optimistic with rollback + inline error on failure.
- **Guest** (§5.4 / P9-07): MemoryPanel detects guest role up front and renders a sign-in state
  without issuing the 403-bound call, so no raw error is surfaced.

## How to verify
- `cd frontend && npm run lint && npm run type-check && npm test -- --watchAll=false`
- Manual: sign in → header `Memory` → edit/save preferences, delete a learned memory; in chat, send
  a message, 👍/👎 a completed answer, use the reason input and "Try again?"; visit `/memory` as a
  guest to see the sign-in state.

## Tests (final step — mandatory)
- `npm run lint` → No ESLint warnings or errors.
- `npm run type-check` (`tsc --noEmit`) → clean.
- `npm test -- --watchAll=false` → **23 suites / 216 tests passed**, incl. the 4 new/extended files.
- No failures; nothing to root-cause.

## Self-check
- [x] Meets acceptance criteria (message_id threading; thumbs on done not streaming; feedback POST +
      reflected state; 👎 → Try again re-send; memory page prefs edit + memory delete; guest state;
      component/unit tests for each).
- [x] No secrets committed; client layer holds no auth (BFF injects Authorization); Router→Service
      layering untouched (frontend-only task, consumes existing APIs).
- [x] Tests/lints pass (pasted above).
