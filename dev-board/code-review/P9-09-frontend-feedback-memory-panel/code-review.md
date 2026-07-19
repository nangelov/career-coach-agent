# Code review — P9-09-frontend-feedback-memory-panel · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend/components/Chat.tsx:~600 | "Try again?" is gated on `rating === "down"`, which is only set *after* the down-vote POST resolves; the reason input (`showReason`) appears immediately on click. If the POST fails, the reason box shows but "Try again?" never does — a small inconsistency. | Optional: gate "Try again?" on the click intent (e.g. `showReason`) rather than the confirmed server rating so regenerate stays available even if the feedback write failed. |
| C2 | nit | frontend/components/MemoryPanel.tsx:343 | `created_at` is rendered as the raw ISO string (`· 2026-07-18T…Z`) with no formatting. | Optional: format with `toLocaleDateString()` for readability. |
| C3 | nit | frontend/components/Chat.tsx (feedback reason "Send") | After a reason is submitted via "Send", there is no visible confirmation the note was saved (unlike the thumb, which highlights). | Optional: reflect a "saved" acknowledgement or clear/collapse the reason input on success. |

## Notes
- **Wire parity verified field-for-field** against the backend schemas: `lib/memory.ts` vs `backend/app/schemas/memory.py` (`Preferences` tone/formality/language/focus_areas/avoid; `LearnedMemory` id/text/memory_type/confidence/created_at; `MemoryView`; `ClearMemoriesResponse.deleted`) and `lib/messageFeedback.ts` vs `backend/app/schemas/message_feedback.py` (`MessageFeedbackResponse` message_id/rating/reason/created_at). All snake_case kept so read→edit→PUT round-trips losslessly.
- **Endpoint/method/status parity verified** against `backend/app/api/memory.py` (GET `/api/memory`, PUT `/api/memory/preferences`, DELETE `/api/memory/{id}` → 204, DELETE `/api/memory` → 200 `{deleted}`) and `backend/app/api/message_feedback.py` (POST `/api/messages/{id}/feedback`). Frontend error branching (401/403/404/429) matches the routers' raised codes; `deleteMemory` correctly does not parse the 204 body.
- **Security posture correct**: no client-side token — all calls are same-origin through the BFF catch-all proxy which injects `Authorization` server-side (SEC-04); reason/memory text is rendered as React text (auto-escaped), no `dangerouslySetInnerHTML`.
- **Acceptance criteria met**: `messageId` threaded onto `ChatMessageView` from start/done/cancelled events (all three carry `message_id` per `lib/chatStream.ts`); controls gate on `status === "done" && messageId` (never while streaming); idempotent-upsert reflection via `aria-pressed`; 👎 → inline reason + "Try again?" re-send of the prior user turn via the shared `sendMessage`; `/memory` page mirrors `profile/page.tsx` auth-gating; guest short-circuits the 403 call with an informative state; optimistic delete with rollback. Guest detection reads `session.role` (matches `SessionRole` in `lib/auth.ts`).
- **Guest recall never hits the account API**: `MemoryPanel` returns the sign-in state before any `getMemory()` call for guests — consistent with the P9-07 durable-only contract.
- **Verification reproduced locally**: `jest` on the 4 new/extended suites → 36/36 pass (incl. streaming-vs-done gating, thumbs-up submit, thumbs-down → Try-again re-send); `tsc --noEmit` clean; `eslint` on all changed files clean.
- No new backend surface added; task consumes existing P9-01/P9-05 APIs only. No analytics wiring added (correctly deferred to P11).
