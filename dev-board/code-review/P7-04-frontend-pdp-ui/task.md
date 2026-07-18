# Task P7-04-frontend-pdp-ui — PDP generation UI (stored profile) + download

- **Phase:** P7   **Status:** ENG   **Tags:** (F)

## Scope
Add a Next.js page/component that calls the new `POST /api/pdp` (P7-03) — **no file upload
here**: the form only collects `career_goal` (required), `target_date` (optional date),
`additional_context` (optional) — and lets the user download the resulting PDF. Mirror the
v1 `PDPDialog.tsx` (`legacy-code/frontend/src/components/PDPDialog.tsx`) fields/labels/flow
minus the CV-upload field (the profile is already stored, per P5/P7-03 — no re-upload).

Follow the **existing v2 frontend conventions exactly** (already established by
`app/roles/page.tsx` + `lib/roles.ts` + `app/profile/page.tsx` + `components/CvUpload.tsx`):
- All backend calls go through the same-origin BFF proxy (`credentials: "same-origin"`,
  relative `/api/...` URLs) — **never** touch the session token client-side (SEC-04/§7.2 is
  already wired generically in `app/api/[...path]/route.ts`; it streams any response body,
  including binary, so a PDF response needs no proxy change).
- New `lib/pdp.ts` client module: pure functions with injectable `fetchImpl`/`baseUrl` (DI for
  tests, mirrors `lib/roles.ts`/`lib/profile.ts`), a typed `PdpApiError` carrying HTTP status,
  and a function that posts the form and returns the PDF as a `Blob` (or triggers a browser
  download directly) plus reads the `X-PDP-Status` response header (P7-03: signals
  `role_profile_missing` — the plan is best-effort, not a hard error) so the UI can show a
  banner/notice rather than silently hiding the caveat.
- Handle the backend's documented outcomes (P7-03 `engineer.md`): `200` PDF (trigger
  download, e.g. via an object URL + a synthetic `<a download>` click, matching v1's
  streamed-PDF-download UX), `X-PDP-Status: role_profile_missing` on `200` → show an inline
  notice ("requirements for this role haven't been mined yet — your plan is profile-based
  only"), `422` → "Upload a CV first" (link/point to the profile page), `502` →
  "couldn't generate right now, try again", `429` → rate-limit message (mirror
  `lib/roles.ts`'s `requirementsFallback`/`gapFallback` pattern), `401` → prompt sign-in.
- New page (e.g. `app/pdp/page.tsx`) or a dialog component reachable from the chat/profile UI
  — your call on placement, but it must be reachable without a page reload from somewhere a
  logged-in user naturally is (chat page and/or profile page are the two candidates already
  in the nav). Guests should see a clear "sign in to generate a PDP" state (mirrors
  `UpgradePrompt.tsx`'s existing pattern) since P7-03 rejects guests with 403.
- Loading state while the request is in flight (this is a synchronous, potentially
  multi-second LLM call per P7-03 — no polling, just a spinner/disabled-submit state).
- Reuse GA4 event wiring **only if it already exists elsewhere in this frontend** (P11 owns
  reintroducing GA4 generally) — do not add a bespoke analytics integration here if the
  codebase doesn't have one yet; check first and note what you found.

## Acceptance criteria
- [ ] A logged-in user can enter career goal (+ optional target date / context) and download a
      generated PDF without ever re-uploading a CV.
- [ ] All backend response cases (200, 200+role_profile_missing, 401, 403, 422, 429, 502) map
      to a clear, distinct UI state — no raw/uncaught fetch errors shown to the user.
- [ ] Guests see a sign-in prompt instead of a broken form (mirrors `UpgradePrompt.tsx`).
- [ ] `lib/pdp.ts` has unit tests (mirrors `lib/roles.ts` / `lib/profile.ts` test style —
      injected `fetchImpl`, no real network) covering the success + error-status branches.
- [ ] Component-level test(s) for the form (mirrors existing `__tests__` for `CvUpload`/
      `RoleRequirements` if present) covering at least the happy path and one error path.

## Design references
- `dev-board/plan.md` / `dev-board/tasks.md` — P7 item: "PDP generation UI (uses stored
  profile) + download."
- `legacy-code/frontend/src/components/PDPDialog.tsx` — v1 fields/labels/flow (parity
  baseline, minus the CV upload field).
- `frontend/lib/roles.ts`, `frontend/components/RoleRequirements.tsx`,
  `frontend/app/roles/page.tsx` — the client-API + page conventions to mirror.
- `dev-board/code-review/P7-03-pdp-endpoint/engineer.md` — the exact request/response
  contract (fields, status codes, `X-PDP-Status` header) this UI talks to.

## Constraints / non-goals
- Do not add a CV-upload field to this form — the profile is already stored (P5); if no
  profile exists the backend returns 422 and the UI should point the user at the existing
  profile/upload page, not re-implement upload here.
- Do not implement dashboard goal/task seeding from the generated PDP — that is P8.
- Do not modify the generic BFF proxy (`app/api/[...path]/route.ts`) unless you find it
  genuinely cannot pass through a binary PDF response — verify first (it already strips only
  `content-encoding`/`content-length`/`transfer-encoding`/`connection` and streams the body
  verbatim), and document your finding either way in the report.
