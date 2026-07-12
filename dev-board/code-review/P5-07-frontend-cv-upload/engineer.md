# Engineer report — P5-07-frontend-cv-upload · Revision 1

## Summary
Added the frontend surface for the P5-04/05/06 backend: a CV upload flow with async parse-progress
polling, and a structured-profile view/edit page. All new code follows the established
`lib/`-as-thin-API-client and DI conventions (`lib/auth.ts` / `lib/chatStream.ts`), attaches the
bearer token via the shared `authHeaders`, and surfaces the backend's distinct rejection states
(401/403/413/415/429) as clear messages rather than raw errors.

## Files changed
- `frontend/lib/profile.ts` (new) — thin API client for the whole `/api/profile` surface plus the
  generic job poller: `uploadCv`, `pollJobStatus`, `pollJobUntilTerminal` (interval-based,
  cancellable via `AbortSignal`), `getProfile`, `updateProfile`. Wire types mirror the backend
  Pydantic schemas verbatim (`ProfileSchema`, `JobStatusResponse`, `CvUploadResponse`); defensive
  `parseProfile`/`parseJobStatus` mappers; typed `ProfileApiError` carrying HTTP status; `isProfileEmpty`.
- `frontend/components/CvUpload.tsx` (new) — file picker + Upload button + polling progress indicator
  (renders `stage`/`message` live, no page reload); success banner (calls `onParsed`); client-safe
  error surface. Aborts the poll on unmount.
- `frontend/components/ProfileView.tsx` (new) — reads the profile via `getProfile`, renders
  editable skills/experience/education/goals, saves via `updateProfile`. Handles the empty
  ("no profile yet") response with an upload prompt; shows a guest note and surfaces the guest-403
  save rejection as a clear message.
- `frontend/app/profile/page.tsx` (new) — App Router route hosting both components; auth-gated
  client-side (mirrors `Chat`); `onParsed` bumps a reload key so the view re-fetches without reload;
  "Back to chat" link.
- `frontend/components/Chat.tsx` — added a "Profile" nav `Link` to `/profile` in the header.
- `frontend/__tests__/profile.test.ts`, `CvUpload.test.tsx`, `ProfileView.test.tsx` (new) — unit
  tests for the client (mocked `fetch`), the upload happy/error/guest paths, and the view read/edit/
  save/guest-403/reload paths.

## Key decisions
- **Wire-verbatim TS types (snake_case) for `Profile`** (design refs: `ingestion/profile.py`,
  `lib/chatStream.ts` convention of mirroring the wire). A `GET` result is edited and `PUT` straight
  back with no lossy field remap, matching how `chatStream` mirrors `ChatEvent`. Skills/goals are
  edited as one-per-line textareas; experience/education as add/remove rows.
- **Typed `ProfileApiError(status, message)`** instead of chatStream's synthetic-event approach:
  these are plain request/response calls (not a stream), so throwing a status-carrying error is the
  KISS analogue of `auth.ts`'s throw-on-non-2xx, and lets the UI branch on 403/413/415/429. Backend
  `detail` is preferred, with friendly fallbacks per status.
- **`pollJobUntilTerminal` in the lib** (task requirement: don't make callers hand-roll `setInterval`).
  Interval-based, invokes `onUpdate` per poll, resolves on `success`/`failure`, cancellable via
  `AbortSignal` (rejects with an `AbortError`, distinguishable via `isAbortError`). `CvUpload` aborts
  it on unmount to avoid state-after-unmount.
- **Guest vs. user** (backend contract): `getProfile` returns 200-empty for guests (no 404), so the
  view always renders; `PUT` is 403 for guests — surfaced pre-emptively via a guest note and on-save
  via the backend's sign-in message, not a generic error.
- **No new dependencies / styling framework** — reused the existing Tailwind utility styling and the
  shared `authHeaders`/`Session` from `lib/auth.ts`.

## How to verify
- `cd frontend && npm run lint && npm run build && npm test`.
- Manual: sign in (or guest) → header "Profile" link → `/profile` → pick a CV → Upload → watch the
  progress stage update → on success the profile view refreshes; edit skills and Save; reload the
  page and the saved data is re-fetched via `GET /api/profile`. As a guest, Save shows the sign-in
  message (403) rather than a raw error.

## Tests (final step — mandatory)
- `npm run lint` → `✔ No ESLint warnings or errors`.
- `npm run build` → compiled successfully; `/profile` route emitted (5.86 kB).
- `npm test` → 9 suites, **89 passed** (30 new across the 3 new files). No failures; nothing skipped.

## Self-check
- [x] Meets acceptance criteria (upload+progress no-reload; view/edit/save + reload persistence for
  users; guest upload-once + guest-403 shown clearly; DI/testable like chatStream/auth; lint+build+test green).
- [x] No secrets committed; frontend-only, no backend changes; `lib/` (API client) vs `components/`
  (React) layering respected, mirroring the backend Router→Service split.
- [x] Tests/lints/build pass (output pasted above).
