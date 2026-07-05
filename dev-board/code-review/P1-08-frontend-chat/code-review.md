# Code review — P1-08-frontend-chat · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | frontend/components/Chat.tsx:158-165 | `handleStop` awaits `cancelChat` with no `try/catch`; the click handler is `() => void handleStop()`. If the cancel POST rejects (network failure), it becomes an unhandled promise rejection, and since no `cancelled` event will then arrive the turn stays stuck in `streaming` (`isStreaming` never clears → Stop button hangs, no user-visible feedback). | Wrap `cancelChat` in `try/catch`; on failure surface a visible state (e.g. flip the turn to `error`/`cancelled` and clear `isStreaming`) so a failed cancel doesn't hang or throw. |
| C2 | nit | frontend/components/Chat.tsx:148-156 | `streamChat` is never passed an `AbortSignal` (the lib supports `options.signal`), so unmounting the component mid-stream leaves the reader running and fires `onEvent`→`setState` on an unmounted tree. React 18 no-ops this, but it holds the response open and logs a warning. | Optionally thread an `AbortController` through a cleanup effect and pass `signal` to `streamChat`, aborting on unmount. |
| C3 | nit | frontend/components/Chat.tsx:20,104 | `ToolStep.result` is populated from `tool_result.content` but never rendered anywhere. | Remove the dead field, or render it (e.g. tooltip/expandable) if visibility of tool output is intended. |
| C4 | nit | frontend/components/Chat.tsx:252 | React `key={step.id}` uses the raw tool-call id, which the parser coerces to `""` when the backend omits `id`; two id-less tool calls would collide as keys. Low real-world risk given the backend always sets `id`. | Fall back to a synthetic index/uuid when `id` is empty. |

## Notes
- Ran the gates from `frontend/`: `npm run type-check` clean, `npm run lint` → "No ESLint warnings or errors", `npm test` → 3 suites / 18 tests pass. Engineer's pasted results reproduce exactly.
- Wire contract verified against source, not prose: `lib/chatStream.ts` event union matches `backend/app/schemas/chat.py` field-for-field (start/token/tool_call/tool_result/done/cancelled/error), and the parser correctly reconstructs the `event` discriminator from the `event:` line because `backend/app/api/chat.py:_format_sse` serialises `data` with `exclude={"event"}`. Frame format `event: <name>\ndata: <json>\n\n` matches the parser's `\n\n` splitting.
- Parser robustness is solid and well-tested: chunk-boundary reassembly (incl. CRLF spanning a boundary, since normalization runs on the concatenated buffer), multi-event chunks + partial tail, malformed-JSON skip, unknown-event forward-compat skip. `TextDecoder({stream:true})` + a final flush handles multi-byte boundaries.
- Security: no `dangerouslySetInnerHTML`; all streamed content (tokens, tool names) rendered as escaped text. `session_id` is client-generated (`crypto.randomUUID`, documented P3 stand-in) and the cancel URL uses `encodeURIComponent`. No secrets, no arbitrary code execution, no committed build artifacts (`git status` clean of node_modules/.next/env). Same-origin `/api` via the dev proxy — no base URL leakage.
- Concurrency: single in-flight turn is enforced (input + Send disabled while `isStreaming`, `handleSend` early-returns), so `updateAssistant` always targeting the last message is safe. Terminal events (`done`/`cancelled`/`error`) end the stream and `isStreaming` clears in `finally`, so the UI recovers and Send reappears.
- Minor design-adjacent observation (system-architect's lane): a stream that closes cleanly without a terminal `done` would leave the turn visually in `streaming` ("Thinking…"); backend always emits a terminal event today, so this is latent, not a live bug.
- Layering matches the task: transport in `lib/chatStream.ts` (no React), UI in `components/Chat.tsx`, thin `app/page.tsx`. SSE parsing is unit-tested independent of the component (acceptance criterion met).

All findings are minor/nit — none gate. Recommend the engineer address C1 (cheap robustness win) in a follow-up or next revision; C2–C4 are optional.
