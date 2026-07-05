# Engineer report — P1-08-frontend-chat · Revision 1

## Summary
Built the first real Next.js (App Router) page: a streaming chat UI that talks to the backend's
`POST /api/chat` SSE endpoint and `POST /api/chat/{session}/cancel` (backend P1-04/P1-06/P1-07). The
placeholder `app/page.tsx` now renders a `<Chat />` client component. Transport logic lives in a thin,
reusable `lib/chatStream.ts` (SSE frame parser + `streamChat`/`cancelChat`), separate from the
`components/Chat.tsx` UI — mirroring the backend's Router→Service split (task requirement; §8 structure
`frontend/app`, `components/`, `lib/`).

Delivered against the wire contract as the single source of truth (the three backend engineer reports):
token-by-token render, visible tool-step indicators, a stop button that cancels and reflects the terminal
`cancelled` event, and a visible (non-crashing) error state for `error` events. `session_id` is generated
client-side (`crypto.randomUUID`, persisted in `sessionStorage`) — the documented stand-in until P3 auth.

## Files changed
- `frontend/lib/chatStream.ts` — **new.** Typed `ChatStreamEvent` union (mirrors `backend/app/schemas/chat.py`),
  a pure `createSSEParser()` (buffers partial frames across chunk boundaries; reconstructs each event from the
  `event:` line + the `event`-less `data:` JSON the backend emits), `streamChat()` (fetch + `ReadableStream`
  reader), and `cancelChat()`.
- `frontend/components/Chat.tsx` — **new.** `"use client"` chat component: message list, input, Send/Stop
  buttons, streaming token render, inline tool-step indicators, stopped/error states, client-side session id.
- `frontend/app/page.tsx` — replaced the P0 stub; now renders `<Chat />`.
- `frontend/jest.setup.ts` — polyfill `TextEncoder`/`TextDecoder` from Node `util` (jsdom omits them; the SSE
  client decodes the response body with `TextDecoder`).
- `frontend/__tests__/chatStream.test.ts` — **new.** 12 tests for the parser (each event type, chunk-boundary
  reassembly, multi-event chunks + partial tail, CRLF tolerance, malformed-JSON skip, unknown-event skip) and
  `streamChat`/`cancelChat` (payload/URL, ordered events, non-2xx → error, network reject → error, abort quiet,
  cancel URL).
- `frontend/__tests__/Chat.test.tsx` — **new.** 4 component tests (incremental token render, tool-step
  indicator, stop → cancel call + `cancelled` reflected with partial preserved, `error` → visible alert).
- `frontend/__tests__/page.test.tsx` — updated to the new chat page (heading + empty-state prompt).

## Key decisions
- **POST SSE via `fetch` + `ReadableStream`, not `EventSource`.** `EventSource` is GET-only, so it cannot
  consume `POST /api/chat`. `streamChat` reads `response.body.getReader()` incrementally, decodes with a
  streaming `TextDecoder`, and feeds a hand-rolled frame parser (task called this out explicitly).
- **Parser reconstructs the `event` field.** The backend's `_format_sse` serialises `data` with
  `exclude={"event"}`, so the JSON payload has no `event` key — the parser reads the SSE `event:` line as the
  discriminator and merges it with the parsed `data:` JSON into a fully-typed event. Verified against the exact
  frames in P1-04's report.
- **Parser is a pure, stateful `push(chunk) → events[]`** — unit-tested independent of fetch/DOM (acceptance
  criterion), including split-mid-frame and multi-event-per-chunk cases. Malformed JSON / unknown event names
  are skipped rather than crashing the stream (forward-compatible).
- **Single error code path.** Non-2xx responses and network rejections are surfaced as a synthetic terminal
  `{event:"error"}` (same shape as the backend's `error` event), so the component has one place to render an
  error. Aborted fetches resolve quietly (no spurious error on unmount/cancel).
- **Stop button = cancel endpoint only.** Clicking Stop calls `POST /api/chat/{session}/cancel` (202); the UI
  then reacts to the backend's terminal `cancelled` event (marks the turn "Stopped", keeps the partial answer
  as-is) rather than tearing down the fetch locally — matching P1-06's design where the backend drives the
  terminal event and closes the stream.
- **Tool steps rendered inline, distinct from answer text** (§3 visibility goal): `tool_call` →
  "🔧 calling `<name>`…", flipped to "✓ `<name>` done" on the matching `tool_result` (`id` ↔ `tool_call_id`),
  in an amber pill above the answer bubble.
- **Client-owned `session_id`.** `crypto.randomUUID()` persisted in `sessionStorage`, set in a mount effect to
  avoid an SSR/hydration mismatch. Deliberate, documented stand-in until P3 auth/session creation.
- **Thin page, reusable lib, UI in `components/`** — the layering the task and §8 ask for; no transport logic
  in the component, no React in the lib.

## How to verify
From `frontend/`:
```bash
npm run type-check   # tsc --noEmit
npm run lint         # next lint
npm test             # jest
npm run build        # next production build
```
Results (Node 18.19.1):
- `type-check` → clean (no output / exit 0)
- `lint` → `✔ No ESLint warnings or errors`
- `test` → `Test Suites: 3 passed, Tests: 18 passed` (no `act(...)` warnings)
- `build` → compiles; `/` prerendered static, 105 kB First Load JS

**Manual live check** (backend running per P1-04's report, real HF token + Redis): `npm run dev`, open the app,
send "What is the date and time in Sofia right now?" — tokens stream in, a `current_date_and_time` tool pill
shows "calling…" then "✓ done", the answer completes. Click **Stop** mid-generation on a long prompt: the turn
freezes with the partial text and a "Stopped" note. Kill the backend and send: a red error alert appears
(no console-only failure).

## Self-check
- [x] Chat sends `POST /api/chat` and renders the answer token-by-token as it streams.
- [x] A tool call shows a visible tool-step indicator distinct from the answer text.
- [x] Stop calls the cancel endpoint for the in-flight `session_id`; UI reflects `cancelled` cleanly (no hang,
      no crash; partial answer preserved).
- [x] An `error` event renders a visible error state, not a console-only failure.
- [x] SSE parsing lives in `frontend/lib/`, unit-tested independent of the UI component.
- [x] `npm run lint`, `npm run type-check`, `npm test` all pass (output pasted); production `build` also passes.
- [x] No secrets committed; same-origin `/api` (dev proxy from `next.config.ts`, no base-URL/CORS config).
- [x] Layering respected — thin `app/page.tsx`, reusable `lib/chatStream.ts`, UI in `components/Chat.tsx`.

## Notes for reviewers
- **jsdom polyfill:** `TextEncoder`/`TextDecoder` added in `jest.setup.ts` because jest-environment-jsdom omits
  them and the SSE client decodes bytes; guarded so it never overrides a real global.
- **`ChatRequest.history` not sent.** Server-side session memory (P1-05) is the source of truth; the frontend
  keys turns by `session_id` and omits `history` (the backend's documented default). No cross-refresh history
  reload UI — explicitly a non-goal here.
- **Out of scope (per task):** no auth/session-creation (P3), no 👍/👎 feedback UI (P9), no dashboard/PDP/
  job-search UI (P1 is chat-only). `message_id` from `start`/`done`/`cancelled` is threaded through the turn
  state but not yet surfaced in UI — it's ready for the P9 feedback control.
