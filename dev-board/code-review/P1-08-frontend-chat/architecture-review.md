# Architecture review — P1-08-frontend-chat · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure — frontend | SSE api client in `frontend/lib/`, UI in `components/`, thin route in `app/` | `lib/chatStream.ts` (transport), `components/Chat.tsx` (UI), `app/page.tsx` renders `<Chat/>` | none — exact §8 placement (lib = "api client (SSE)") |
| A2 | Layering (Router→Service split analogue) | transport logic separate from the React component; no React in lib, no fetch/parse in component | component calls `streamChat`/`cancelChat`; lib is pure TS + DOM `fetch`, no React import | none |
| A3 | §9 API surface | `POST /api/chat`, `POST /api/chat/{session}/cancel` | lib posts `/api/chat` and `/api/chat/${session}/cancel` (202-driven) | none — paths match backend `api/chat.py` (`prefix="/api"`) |
| A4 | Wire contract fidelity | mirror `schemas/chat.py` `ChatEvent` union + `ChatRequest{session_id,message,history?}` | `ChatStreamEvent` union field-for-field identical (start/token/tool_call/tool_result/done/cancelled/error); payload `{session_id,message,history?}` | none — every field name and shape matches the backend model |
| A5 | POST-SSE transport (task note) | `fetch`+`ReadableStream` reader, not GET-only `EventSource`; hand-rolled `event:`/`data:` frame parse | `streamChat` reads `response.body.getReader()` + streaming `TextDecoder` + pure `createSSEParser` reconstructing `event` from the `event:` line (backend emits `data` with `exclude={"event"}`) | none — parser matches backend `_format_sse` exactly |
| A6 | Interface-before-impl seam | reusable transport seam, testable independent of UI | pure stateful `push(chunk)→events[]`, injectable `fetchImpl`/`signal`/`baseUrl`; single synthetic terminal `error` code path | none |
| A7 | Phase fit — no premature coupling | P1 chat-only; no P3 auth, no P9 feedback | client-owned `session_id` (`crypto.randomUUID`+sessionStorage) as documented P3 stand-in; `message_id` threaded through turn state but not surfaced (ready, not coupled, for P9) | none |
| A8 | Data ownership §4 | guest turns keyed by session_id (Redis-only, backend-side) | frontend touches no store; owns only a client session id, defers memory to server (P1-05); `history` omitted so server session memory is source of truth | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — lib/component/app split mirrors Router→Service; no leakage either way.
- [x] Honors locked decisions — SSE streaming chat via Next.js App Router; POST-SSE via fetch (not EventSource); no ReAct/Mongo concerns apply to this layer.
- [x] Interfaces-before-implementations — `SSEParser` + injectable `fetchImpl` make the transport a real, swappable, unit-tested seam.
- [x] Budget posture — OSS/self-hosted only; no paid SDKs or hosted SSE helpers pulled in (hand-rolled parser).

## Notes
- Design-clean. `baseUrl` defaults to same-origin, relying on the dev-only `/api/:path*` rewrite in `next.config.ts`; prod serving is a P11 concern and the `baseUrl` override already leaves that seam open — no action now.
- `session_id` client generation and `history` omission are both correctly scoped as documented interim stand-ins for P3 (auth/session) and P1-05 (server memory) respectively — no later-phase coupling introduced.
- `message_id` is carried in turn state but intentionally not rendered; this is the correct posture for P9 feedback (surface later, don't build the control now). Logged as a P9 follow-up, not a gap.
- Correctness/coverage of the parser and component tests are the code-reviewer's remit (running in parallel); this review does not opine on them.
