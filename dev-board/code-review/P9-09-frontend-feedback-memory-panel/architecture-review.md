# Architecture review — P9-09-frontend-feedback-memory-panel · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 App Router structure | new feature lives in `app/<route>/page.tsx` + `components/` + `lib/` client layer | `app/memory/page.tsx` (shell), `components/MemoryPanel.tsx`, `lib/memory.ts` + `lib/messageFeedback.ts`; mirrors `app/profile`, `lib/dashboard` conventions | none |
| A2 | BFF session transport (SEC-04 / §7.2) | no client-side auth; token stays in httpOnly cookie; BFF injects `Authorization` server-side | both `lib/` clients are token-free, `credentials: same-origin` on same-origin `/api/...` fetches; routed through catch-all `app/api/[...path]/route.ts` (exports GET/POST/PUT/DELETE/PATCH) — no new BFF handlers | none — matches blessed [bff-session-transport] |
| A3 | Wire contract fidelity | `lib/` types mirror backend Pydantic verbatim (snake_case) | `Preferences`/`LearnedMemory`/`MemoryView` == `schemas/memory.py`; `MessageFeedback` == `MessageFeedbackResponse`; embedding excluded (§7.6) | none |
| A4 | Endpoint paths | consume existing P9-01/P9-05 routes only | GET `/api/memory`, PUT `/api/memory/preferences`, DELETE `/api/memory/{id}`, DELETE `/api/memory`, POST `/api/messages/{id}/feedback` — all match live routers exactly | none |
| A5 | §6.10 silent-but-viewable/deletable, no per-fact confirmation | view/edit prefs + immediate per-item delete; no approve/reject | optimistic delete w/ rollback, immediate PUT (full-replace) save, no confirmation dialog, no propose/approve UI | none — matches [memory-crud-panel] ruling (PUT prefs = full replace, no-confirmation opt-out) |
| A6 | Guest personalization (§5.4 / P9-07) | guest gets a clear account-only state, not a raw 403 | `MemoryPanel` short-circuits on `session.role === "guest"`, never issues the 403-bound call; renders sign-in state | none — Redis-only-until-upgrade rule honored |
| A7 | §5.5 response feedback + inline regenerate | 👍/👎 on completed turns, idempotent reflection, 👎 → inline "Try again?" | controls gate on `status === "done" && messageId`; `aria-pressed` reflects stored rating; 👎 reveals reason input + Try again re-sends prior user turn via existing streaming path | none |
| A8 | No new backend surface / no analytics | frontend-only; try-again = re-send, no regenerate endpoint; no GA4 (P11) | confirmed — `sendMessage` reuses existing SSE path; no analytics wiring added | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — transport in `lib/`, UI in `components/`, thin `app/` shell (consistent with blessed [frontend-sse-pattern]); no cross-layer leak
- [x] Honors locked decisions — SSO-only session via BFF cookie; no new auth surface; consumes Postgres-backed memory only through the API
- [x] Interfaces-before-implementations — client layer keeps injectable `fetchImpl`/`baseUrl` seam; UI depends on typed `lib/` functions, not raw fetch
- [x] Budget posture respected — no new services/deps

## Notes
- `deleteAllMemories` is implemented in `lib/memory.ts` but not surfaced in the panel UI. Task marked it optional; leaving the seam unused is acceptable (not dead-weight — it maps to the live `DELETE /api/memory` route). No action required.
- `created_at` renders as the raw ISO string in the learned-memory list — a cosmetic UX nit, not a design concern; owner of a follow-up polish pass if desired.
- Message-id threading correctly stamps from `start`/`done`/`cancelled`; guardrail/off-topic/error turns that emit a terminal event with an id get the same controls, consistent with the P9-01 capture contract.
