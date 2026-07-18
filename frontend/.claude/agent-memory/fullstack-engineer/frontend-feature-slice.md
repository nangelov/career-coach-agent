---
name: frontend-feature-slice
description: The required shape for a new frontend feature over a backend /api/* surface (client lib, route page, component, tests)
metadata:
  type: feedback
---

Every new frontend feature over a backend `/api/*` surface mirrors the roles/profile slice shape exactly.

**Why:** the code-reviewer/system-architect gate on conformance to existing idioms, not just correctness — divergence draws CHANGES_REQUESTED even when the code works.

**How to apply:**
- `lib/<feature>.ts` — pure functions with injectable `{ baseUrl?, fetchImpl? }` (DI, no hard globals); `credentials: "same-origin"`; NO client-side auth header (the catch-all BFF proxy at `app/api/[...path]/route.ts` injects `Authorization` from the httpOnly cookie for ALL verbs — no per-route allowlist to update). Wire types mirror backend Pydantic verbatim (snake_case). A typed `<Feature>ApiError extends Error` carrying `status`. Defensive `raw: unknown → typed` parsers that degrade missing fields. Best-effort `{detail}` extraction for messages.
- `app/<feature>/page.tsx` — hydrate via `fetchSession()`; `if (!authChecked) return null;` then `<Login>` when no session. Guest-gated features render a sign-in gate INSIDE the component (mirror `PdpGenerator`'s `GuestGate` / `upgradeGuestToSso` → `beginSsoLogin` fallback), never a raw 403.
- Primary nav links live only in `components/Chat.tsx` header; other pages just link "Back to chat".
- Tests: `lib/*.test.ts` uses an injected fake `fetchImpl` + a `jsonResponse` stand-in; component tests `jest.mock("@/lib/<feature>")` and drive real approve/reject/create flows. Run `npx tsc --noEmit`, `npm run lint`, `npm test` (the exact frontend-ci.yml commands) before handoff.
