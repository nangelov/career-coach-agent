# Task P9-09-frontend-feedback-memory-panel — 👍/👎 + try again + memory panel
- **Phase:** P9   **Status:** ENG   **Tags:** (F)

## Scope
Frontend for the whole P9 personalization/feedback surface: per-message 👍/👎 (+ inline
"try again") on assistant messages, and a "What the coach knows about you" panel backed by the
`GET/PUT/DELETE /api/memory` API (P9-05).

From `dev-board/tasks.md` (P9):
> 👍/👎 on messages + inline "try again"; "What the coach knows about you" panel.

### What already exists (read before building)
- `frontend/components/Chat.tsx` — `ChatMessageView` (no `messageId` field yet — the streamed
  `DoneEvent`/`CancelledEvent` already carry `message_id`, see `frontend/lib/chatStream.ts`;
  thread it onto `ChatMessageView` so the UI can address a specific assistant message).
  `AssistantBubble` (line ~420) is where the citations/plan/tool-step indicators already render
  per assistant message — add the 👍/👎 + "try again" controls there, once `message.content` is
  final (`status === "done"` — no reacting to a message still streaming).
  The header (line ~301–341) already has `Dashboard` / `Roles` / `Profile` / `Plan` nav links —
  add a `Memory` link there pointing at a new `/memory` route, matching that exact pattern.
- `frontend/app/profile/page.tsx` — the page-shell pattern to mirror for the new
  `frontend/app/memory/page.tsx`: hydrate session via `fetchSession()` (BFF, httpOnly cookie,
  SEC-04), show `Login` when unauthenticated, render the feature component when signed in.
  **Guests get `403` from `GET /api/memory`** (P9-05) — the memory panel is an
  account-only feature; render a clear "sign in to see what the coach has learned" state for a
  guest rather than erroring.
- `frontend/lib/dashboard.ts` / `frontend/lib/roles.ts` / `frontend/lib/profile.ts` — the
  **client API-layer convention** to mirror exactly for new `frontend/lib/memory.ts` (memory
  panel: `getMemory`, `updatePreferences`, `deleteMemory`, optionally `deleteAllMemories`) and
  `frontend/lib/messageFeedback.ts` (`submitMessageFeedback(messageId, rating, reason?)`):
  injectable `fetchImpl`/`baseUrl`, no client-side auth (BFF injects `Authorization`
  server-side), wire types mirroring the backend Pydantic schemas verbatim, a typed
  `*ApiError` carrying HTTP status.
- `backend/app/schemas/message_feedback.py`, `backend/app/schemas/memory.py` (or wherever P9-05
  put its response models — check) — the exact wire shapes these two new `lib/` modules must
  mirror.
- `frontend/components/UpgradePrompt.tsx` / the existing rate-limit banner in `Chat.tsx` — an
  example of a dismissible inline banner component, useful if "try again" needs a lightweight
  confirmation/loading state.

## Acceptance criteria
- [ ] `ChatMessageView` carries the turn's `message_id` (from `DoneEvent`/`CancelledEvent`);
      guardrail/off-topic/error turns that still stamp a `message_id` are handled the same way.
- [ ] Each **completed** (`status === "done"`) assistant message shows 👍 / 👎 buttons. Clicking
      one calls `POST /api/messages/{message_id}/feedback` (P9-01) with `rating` (+ optionally
      prompts for a one-line reason on 👎 — a simple inline text input is enough, no modal
      required). Reflects the stored state (button shows selected/highlighted after submit;
      resubmitting/toggling updates it, matching the backend's idempotent upsert).
- [ ] A 👎 also surfaces an inline **"Try again?"** affordance (§5.5: "a down-vote can trigger an
      inline 'want me to try again?' regenerate"). Wire it to re-send the same user turn (you
      already have `handleSend`/the turn's original user message in scope) — a full re-answer
      through the existing streaming path is an acceptable implementation (no new backend
      "regenerate" endpoint is being added in this task; if the existing send path doesn't
      cleanly support "regenerate last turn", note the gap in `engineer.md` rather than
      inventing new backend surface).
- [ ] `/memory` page: shows explicit `preferences` (editable — simple form fields matching
      whatever shape P9-05 exposes: tone/formality/language/focus areas/do-don't list) and the
      list of learned `memories` (text + type + confidence + created_at), each with a **Delete**
      button (immediate — no confirmation dialog, per §6.10 "no per-fact confirmation prompts";
      a lightweight "Undo"-style toast is fine if trivial, but not required). No approve/reject
      workflow of any kind — contrast with the P8 dashboard's propose/approve UI, which does not
      apply here.
- [ ] Guest visiting `/memory` sees a clear informative state (not a raw 403/error): guests have
      no durable memory yet (P9-07 — personalization is session-only until upgrade).
- [ ] Basic component/unit tests (mirroring the existing frontend test conventions — check
      `frontend/**/*.test.tsx` for the pattern) for: rendering thumbs on a done message but not a
      streaming one, submitting feedback, the memory list rendering + delete action, the guest
      empty-state.

## Design references
- dev-board/app-design-and-features.md: §5.5 (response feedback + inline regenerate), §5.4 point
  4 (memory panel: "view, edit, and delete learned memories"), §6.10 (silent-but-viewable/
  deletable, no per-fact confirmation).
- `backend/app/api/message_feedback.py`, the P9-05 memory router (check its exact module name/
  path under `backend/app/api/`).
- `frontend/components/Chat.tsx`, `frontend/lib/dashboard.ts` (conventions to mirror).

## Constraints / non-goals
- No new backend endpoints — this task consumes the existing P9-01/P9-05 APIs only.
- No GA4/analytics event wiring — that's P11 (§6.27), even though the task list mentions
  thumbs-up/down as a future GA4 event category; don't add analytics here.
- No changes to the dashboard, roles, PDP, or profile pages beyond the one new header nav link.
