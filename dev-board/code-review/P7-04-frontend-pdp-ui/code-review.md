# Code review — P7-04-frontend-pdp-ui · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend/lib/pdp.ts:130 | `filenameFromDisposition` calls `decodeURIComponent(match[1])` on the plain-`filename=` branch too; a lone `%` (not a valid escape) would throw a `URIError` and reject the whole success. Unreachable from *this* backend (the P7-03 slug strips all non-word chars, so `%` never appears), but the helper is generic/exported. | Optional hardening: wrap the decode in try/catch and fall back to the raw match, or only decode the `filename*=UTF-8''` branch. Not gating — backend-controlled. |
| C2 | nit | frontend/lib/pdp.ts:99 / __tests__/pdp.test.ts:119 | 403 has a fallback message (`generateFallback`) but no dedicated unit test, and the guest gate makes 403 unreachable via the form. Coverage gap only. | Optionally add a 403 case to the `it.each` for completeness; behavior is already correct. |
| C3 | nit | frontend/components/PdpGenerator.tsx:257 | The success banner + role-missing notice persist unchanged if the user then edits the goal and regenerates only after re-submit; no state reset on field edit. Pure UX polish. | None required; acceptable. |

## Notes
- **Contract parity verified against P7-03** (`backend/app/api/pdp.py`, `backend/app/schemas/pdp.py`):
  request body is snake_case `career_goal` (required) + optional `target_date` / `additional_context`,
  matching `PdpRequest` field-for-field (`target_date` sent as `YYYY-MM-DD`, parsed by Pydantic `date`).
  Response mapping is complete and distinct: 200 (download), 200 + `X-PDP-Status: role_profile_missing`
  (inline notice), 401/403/422/429/502 all keyed on `PdpApiError.status` with backend-`detail`-preferred
  messages. `PdpDeliveryStatus` correctly narrowed to `ok | role_profile_missing` (the only values reachable
  on a 200 — `generation_failed`/`profile_missing` map server-side to 502/422). No unhandled/raw fetch errors.
- **BFF passthrough claim independently confirmed** (`frontend/lib/bffProxy.ts:130-137`): response headers are
  copied from the backend and only a strip-list (`content-encoding`/`content-length`/`transfer-encoding`/
  `connection`) is deleted — so `X-PDP-Status` and `Content-Disposition` reach the browser and the binary PDF
  streams verbatim. No proxy change needed; engineer's decision holds. Same-origin, `credentials: "same-origin"`,
  token never touched client-side (SEC-04) — verified.
- **Conventions mirrored correctly**: injectable `fetchImpl`/`baseUrl` DI, `PdpApiError` carrying status,
  best-effort `readDetail`, pure-fetch + separated `triggerDownload` DOM helper — all match `lib/roles.ts`/
  `lib/profile.ts`. Guest gate reuses the shared `lib/auth.ts` upgrade flow (no duplicated auth logic).
  Reachable via new "Plan" nav link in `Chat.tsx`; `/pdp` page mirrors `/roles` session-hydrate pattern.
- **Security**: no `dangerouslySetInnerHTML`; parsed content rendered as escaped React text; download via
  `download` attribute (not executed); no client-side token. Clean.
- **Verification reproduced locally**: `npx tsc --noEmit` exit 0; `npx jest` on both suites → 16/16 passed;
  `npx next lint` on changed files → no warnings/errors. Matches the engineer report.
