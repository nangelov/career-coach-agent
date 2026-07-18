# Engineer report — P7-04-frontend-pdp-ui · Revision 1

## Summary
Added the v2 PDP generation UI: a logged-in user enters a career goal (+ optional target date /
context) and downloads a generated PDF built from their **stored** profile — no CV re-upload.
Follows the established v2 frontend conventions exactly (`lib/roles.ts`/`lib/profile.ts` client
style; `RoleRequirements.tsx`/`CvUpload.tsx` component style; `app/roles/page.tsx` page style; BFF
same-origin proxy, no client-side token). New `lib/pdp.ts` client + `PdpGenerator` component +
`app/pdp/page.tsx` route, reachable via a new "Plan" nav link in the chat header.

## Files changed
- `frontend/lib/pdp.ts` (new) — client module: `PdpApiError` (carries HTTP status), `generatePdp`
  (pure, injectable `fetchImpl`/`baseUrl`; POSTs the snake_case body, returns the PDF as a `Blob` +
  filename + `X-PDP-Status` delivery status), `filenameFromDisposition`, and `triggerDownload` (the
  only DOM helper — object URL + synthetic `<a download>` click, kept separate so the fetch path is
  pure/testable and mockable under jsdom which has no `URL.createObjectURL`).
- `frontend/components/PdpGenerator.tsx` (new) — the form (career goal required; optional context /
  target date), loading spinner/disabled-submit, success + role-missing notice + per-status error
  states, and a guest sign-in gate.
- `frontend/app/pdp/page.tsx` (new) — the `/pdp` route (session hydrate → Login when no session →
  `PdpGenerator`), mirroring `app/roles/page.tsx`.
- `frontend/components/Chat.tsx` — added a "Plan" nav link (alongside Roles/Profile) so the page is
  reachable without a reload.
- `frontend/__tests__/pdp.test.ts` (new), `frontend/__tests__/PdpGenerator.test.tsx` (new).

## Key decisions
- **Blob-returning pure fetch + separate `triggerDownload`** (task: "returns a Blob … plus reads
  `X-PDP-Status`"). `generatePdp` stays DOM-free and unit-testable; the component composes it with
  `triggerDownload`. Mirrors `lib/auth.ts`'s injectable-navigate precedent for the one DOM edge.
- **All backend outcomes → distinct UI state** (task acceptance / P7-03 contract): 200 → download +
  success banner; 200 `X-PDP-Status: role_profile_missing` → inline "profile-based only" notice
  (blue, links to Roles); 422 → "upload a CV first" + link to `/profile`; 401/429/502 → distinct
  fallback messages keyed on `PdpApiError.status` (mirrors `lib/roles.ts`'s `gapFallback` pattern,
  preferring the backend `detail`). `X-PDP-Status`/`Content-Disposition` are read from the 200
  response; the delivery-status type is narrowed to `ok | role_profile_missing` (the only values
  reachable on a 200 — `generation_failed`/`profile_missing` map to 502/422 server-side).
- **Guest gate, not a broken form** (task; P7-03 → 403 for guests). Guests never see the form; they
  get a sign-in panel mirroring `UpgradePrompt.tsx`'s guest pattern (`upgradeGuestToSso` →
  `beginSsoLogin` fallback) so the guest session carries over. Chose to inline the gate rather than
  reuse `UpgradePrompt` directly because that component's transient "Dismiss" affordance doesn't fit
  a persistent page gate; the shared auth flow (`lib/auth.ts`) is still reused (no duplicated auth
  logic).
- **New page over a chat dialog** — matches the existing `/roles` + `/profile` route+nav pattern
  (KISS/consistency); reachable via the chat header "Plan" link. Optional target date (task says
  optional; v1 required it) with a `min=today` picker mirroring v1.
- **No GA4 wiring added** — I grepped the whole `frontend/` (`gtag`/`analytics`/`GA`): none exists
  in v2 yet (P11 owns reintroducing it). Per the task I did not add a bespoke integration; v1's
  `PDPDialog` `gtag` calls are intentionally dropped for now.
- **No BFF proxy change** — verified `lib/bffProxy.ts` streams the backend body verbatim
  (`ReadableStream`, incl. binary) and strips only `content-encoding`/`content-length`/
  `transfer-encoding`/`connection`, so `Content-Disposition` and `X-PDP-Status` pass through to the
  browser and a PDF streams cleanly. No change needed (confirmed by reading the module + its tests).

## How to verify
```
cd frontend
npx tsc --noEmit
npx jest __tests__/pdp.test.ts __tests__/PdpGenerator.test.tsx
npx next lint --file lib/pdp.ts --file components/PdpGenerator.tsx --file app/pdp/page.tsx
```
Manual: sign in → chat header "Plan" → enter a career goal → Generate PDP downloads the PDF. With
no stored profile the form shows "upload a CV first" linking to `/profile`. As a guest the page
shows the sign-in gate instead of the form.

## Tests (final step — mandatory)
- `npx jest` (full frontend suite) → **18 suites, 167 tests passed** (16 new: 10 in `pdp.test.ts`,
  6 in `PdpGenerator.test.tsx`).
- `npx tsc --noEmit` → clean (exit 0).
- `npx next lint` (changed files) → No ESLint warnings or errors.
- No failures to root-cause.

Coverage: `lib/pdp.ts` — success (POST body shape, no client Authorization, blob + `ok` status +
filename), optional-field omission, `role_profile_missing` header, 422 with backend detail,
401/429/502 distinct fallbacks, `PdpApiError` instance on 500, `filenameFromDisposition`
(plain/UTF-8/fallback). `PdpGenerator` — happy path (generate + download + success), role-missing
notice, 422 → upload-CV message + profile link (no download), submit-disabled-until-goal, guest
sign-in gate (form hidden).

## Self-check
- [x] Meets acceptance criteria: logged-in user downloads a PDF from stored profile (no re-upload);
  all response cases (200 / 200+role_profile_missing / 401 / 403 / 422 / 429 / 502) map to distinct
  UI states with no raw fetch errors; guest sees a sign-in gate; `lib/pdp.ts` unit tests + component
  tests (happy + error paths) added.
- [x] No secrets committed; same-origin BFF proxy used (`credentials: "same-origin"`, relative
  `/api/pdp`), token never touched client-side; no proxy change.
- [x] Tests/lints/types pass (pasted above).
