# Task P1-08-frontend-chat — Next.js streaming chat page
- **Phase:** P1   **Status:** ENG   **Tags:** (F)

## Scope
Build the first real page of the Next.js (App Router) frontend: a chat UI that talks to the backend's
`POST /api/chat` SSE endpoint (P1-04/P1-06/P1-07) and `POST /api/chat/{session}/cancel` (P1-06). Replace the
placeholder `frontend/app/page.tsx` (currently just a "streaming chat UI arrives in P1" stub) with the real
chat page (or add a dedicated route like `app/chat/page.tsx` and link it from `page.tsx` — your call).

Read the backend engineer reports first — they are the authoritative contract:
- `dev-board/code-review/P1-04-chat-endpoint/engineer.md` — request shape (`ChatRequest{session_id, message,
  history?}`), the SSE event vocabulary and exact frame format (`event: <name>\ndata: <json>\n\n`):
  `start`{message_id} · `token`{content} · `tool_call`{id,name,arguments} ·
  `tool_result`{tool_call_id,name,content} · `done`{message_id,finish_reason} · `error`{message}.
- `dev-board/code-review/P1-06-cancel-stream/engineer.md` — the `cancelled`{message_id} terminal event and
  the cancel endpoint (`POST /api/chat/{session}/cancel`, returns 202 promptly).
- `dev-board/code-review/P1-07-message-id/engineer.md` — `message_id` is stable per turn; carried on
  `start`/`done`/`cancelled`.

**Important implementation detail:** `POST /api/chat` is a **POST** SSE stream, so the browser's native
`EventSource` (GET-only) does not work here. Use `fetch()` with a `ReadableStream` reader (or a small
well-vetted helper) to read the response body incrementally and parse `event:`/`data:` frames yourself —
document whichever approach you pick in `engineer.md`.

Build:
- A chat page/component with: a message list (user + assistant turns), an input box + send, and a **stop**
  button that's enabled only while a response is streaming.
- **Streaming render:** assistant text appears token-by-token as `token` events arrive (no waiting for
  `done`).
- **Stop button:** calls `POST /api/chat/{session}/cancel` for the active `session_id`; the UI then reflects
  the `cancelled` terminal event (e.g. show the partial answer as-is, marked "stopped").
- **Visible tool steps:** when `tool_call`/`tool_result` events arrive, render a lightweight inline indicator
  (e.g. "🔧 calling `current_date_and_time`…" → "✓ done") so tool use is visible, not hidden — this is a
  design goal (§3 multi-agent orchestration visibility carries into P1's single-loop version) and matches
  what P1-04's report calls "visible tool steps".
- **Session id:** generate/persist a `session_id` client-side (e.g. `crypto.randomUUID()` stored in
  `sessionStorage` or component state) — there's no auth/session-creation endpoint yet (that's P3), so the
  frontend owns id generation for now.
- **Error handling:** an `error` SSE event (e.g. all LLM models failed) should render a visible, non-crashing
  error state in the UI, not an unhandled promise rejection.
- Keep the SSE client logic in `frontend/lib/` (e.g. `lib/chatStream.ts`) separate from the UI component in
  `frontend/components/` — thin page, reusable lib, consistent with the backend's Router→Service split.
- Tests: component/unit tests (Jest + Testing Library, already wired per P0's frontend CI) for the SSE
  parsing helper (feed it fake chunked text, assert it yields the right typed events) and for basic chat
  component behavior (renders streamed tokens incrementally, shows a tool-step indicator, stop button
  triggers the cancel call). Mock `fetch`; no real backend needed in CI.

## Acceptance criteria
- [ ] Chat page sends `POST /api/chat` and renders the assistant's answer token-by-token as it streams.
- [ ] A tool call during the conversation shows a visible "tool step" indicator distinct from the main answer
      text.
- [ ] Stop button calls the cancel endpoint for the in-flight `session_id` and the UI reflects the
      `cancelled` event cleanly (no hang, no crash).
- [ ] An `error` event renders a visible error state, not a console-only failure.
- [ ] SSE parsing logic lives in `frontend/lib/`, is unit-tested independent of the UI component.
- [ ] `npm run lint`, `npm run type-check`, and `npm test` all pass (P0's frontend CI gates).

## Design references
- dev-board/plan.md: Phase 1 ("Next.js chat page: streaming render, stop button, visible tool steps")
- dev-board/app-design-and-features.md: §8 Target Project Structure (`frontend/app`, `components/`, `lib/`),
  §9 API Surface (`POST /api/chat`, `POST /api/chat/{session}/cancel`)
- dev-board/code-review/P1-04-chat-endpoint/engineer.md, P1-06-cancel-stream/engineer.md,
  P1-07-message-id/engineer.md — the exact request/SSE contract (read all three; this is the frontend's only
  source of truth for the wire format)
- frontend/next.config.ts — the existing dev-only `/api/:path*` rewrite to `localhost:8000` (no CORS/base-URL
  config needed in dev)

## Constraints / non-goals
- No real auth/session creation (`POST /api/auth/guest` etc. is P3) — client-generated `session_id` is a
  deliberate, documented stand-in.
- No message persistence/history reload across page refresh beyond what's trivial (server-side history via
  P1-05 exists, but wiring a "load past session" UI is not required here).
- No feedback (👍/👎) UI — that's P9.
- No dashboard/profile/job-search UI — out of scope, P1 is chat-only.
