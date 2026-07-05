---
name: project-frontend-jest-jsdom
description: Frontend Jest (jest-environment-jsdom) gotchas — TextEncoder/TextDecoder + scrollIntoView missing; act() wrapping for async state
metadata:
  type: project
---

Frontend tests run under **jest-environment-jsdom** (Next 15 + `next/jest`, see `frontend/jest.config.ts`).

**Why:** jsdom omits several browser globals/methods that streaming/DOM code relies on, so tests fail with
`ReferenceError`/`TypeError` even when the code is correct.

**How to apply:**
- `TextEncoder`/`TextDecoder` are **not** defined in jsdom — polyfill them from Node `util` in
  `frontend/jest.setup.ts` (guarded so a real global is never overridden). Needed by any code that decodes a
  `fetch` `ReadableStream` body (e.g. the SSE chat client `lib/chatStream.ts`).
- `Element.prototype.scrollIntoView` is **not** implemented — optional-chain the *method call*
  (`ref.current?.scrollIntoView?.({...})`), not just the ref.
- Async state updates after an `await` (e.g. `setIsStreaming(false)` after `await streamChat(...)`) trigger
  "update not wrapped in act(...)" warnings. Wrap the triggering `fireEvent`/manual event-dispatch in
  `await act(async () => { ... })`. `findBy*`/`waitFor` flush most, but the trailing microtask after an awaited
  call needs an explicit `act`.
- No `@testing-library/user-event` dependency is installed — use `fireEvent`.
