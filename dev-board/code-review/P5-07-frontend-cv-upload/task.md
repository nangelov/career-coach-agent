# Task P5-07-frontend-cv-upload — CV upload UI + progress indicator; profile view/edit
- **Phase:** P5   **Status:** ENG   **Tags:** (F)

## Scope
tasks.md item: "CV upload UI + progress indicator; profile view/edit."

Add the frontend surface for the P5-04/05/06 backend work: uploading a CV, watching it parse
asynchronously, and viewing/editing the resulting structured profile. Follow the existing
`frontend/` conventions (Next.js App Router + TypeScript, `lib/` = thin API-client modules,
`components/` = React, `"use client"` components, DI-friendly `fetchImpl`/options params for
testability — mirror `lib/auth.ts` / `lib/chatStream.ts` exactly) and the existing bearer-token
session handling (`lib/auth.ts`'s `loadSession()` / `Session` type — the same session used by
`components/Chat.tsx`).

Add:
1. **`lib/profile.ts`** — a thin API client mirroring `lib/auth.ts`'s shape/DI conventions:
   - `uploadCv(file, session, options?)` → `POST /api/profile/cv` (multipart), returns the
     `{task_id}` handle (backend `CvUploadResponse` — see `backend/app/schemas/profile.py`).
   - `pollJobStatus(taskId, session, options?)` → `GET /api/jobs/status/{task_id}` (backend
     `JobStatusResponse` — see `backend/app/schemas/jobs.py`); expose a small polling helper
     (interval-based re-fetch until `success`/`failure`, cancellable) rather than making every
     caller hand-roll `setInterval`.
   - `getProfile(session, options?)` → `GET /api/profile` (backend returns the `ProfileSchema`
     shape — see `backend/app/ingestion/profile.py`; mirror its fields in a TS type: skills,
     experience, education, goals).
   - `updateProfile(profile, session, options?)` → `PUT /api/profile`.
   - All authenticated calls attach `Authorization: Bearer <token>` exactly like `lib/chatStream.ts`
     does; handle 401/403/404/413/415/429 the same way existing code surfaces errors to the UI
     (check how `Chat.tsx`/`chatStream.ts` handle rate-limit/auth errors today and stay consistent).
2. **A CV upload component** (e.g. `components/CvUpload.tsx`): file picker, upload button, and a
   progress indicator that polls job status and renders the stage (`pending`/`in_progress` with
   `stage`/`message` from the backend/`success`/`failure`) until done; on success, show a link/
   button to view the parsed profile; on failure, show the client-safe error message.
3. **A profile view/edit component** (e.g. `components/ProfileView.tsx`): renders the structured
   profile (skills/experience/education/goals) read via `getProfile`, and lets the user edit and
   save it via `updateProfile`. Handle the "no profile yet" (empty) response gracefully (prompt to
   upload a CV).
4. **A route** to host these (e.g. `app/profile/page.tsx`, App Router) — reachable from the
   existing chat UI (a simple nav link/button is enough; a full nav bar redesign is out of scope).
   Respect guest vs. logged-in behavior: guests can upload once (P3-04 rate limit) but PUT is
   rejected by the backend (403) for guests — surface that clearly rather than letting it look
   like a generic error.
5. Unit tests (Jest + existing testing-library setup, mirror `__tests__/chatStream.test.ts` /
   `__tests__/auth.test.ts` / `__tests__/Chat.test.tsx` patterns): the `lib/profile.ts` client
   functions (mock `fetch`), the upload component's happy path + error path, and the profile
   view/edit component's read + save flow. Add them under `__tests__/`.

## Acceptance criteria
- [ ] A user can pick a CV file, upload it, and see a progress indicator that updates as the
      backend job progresses (pending → in-progress-with-stage → success/failure), without a page
      reload.
- [ ] On success, the user can view the parsed structured profile (skills/experience/education/
      goals) and edit + save it (`PUT /api/profile`), and reloading the page shows the saved data
      (`GET /api/profile`) — no re-upload required to see/use the profile again.
- [ ] Guest-vs-logged-in behavior matches the backend contract (guest upload allowed once, guest
      `PUT` rejected — shown as a clear message, not a raw error).
- [ ] All new `lib/`/`components/` code follows the existing DI/testability conventions (injected
      `fetchImpl`, no hard `window`/`fetch` globals in pure logic where avoidable) so it's
      unit-testable exactly like the existing `chatStream`/`auth` modules.
- [ ] `npm run lint`, `npm run build` (tsc via Next), and `npm test` all pass, with new tests
      covering the upload flow, polling, and profile view/edit.

## Design references
- dev-board/plan.md: Phase 5 (line 101, frontend implied by exit criteria "usable structured
  profile")
- dev-board/app-design-and-features.md: §5.1, §8 (frontend `lib/`/`components/` structure),
  §9 API table (`POST /api/profile/cv`, `GET/PUT /api/profile`, `GET /api/jobs/status/{task_id}`).
- `frontend/lib/auth.ts`, `frontend/lib/chatStream.ts` — the API-client conventions to mirror
  (DI options, wire-type mapping, bearer-token attach).
- `frontend/components/Chat.tsx`, `frontend/components/Login.tsx` — component conventions
  (`"use client"`, session handling, error surfacing).
- Backend contracts this consumes (already implemented, do not modify):
  `backend/app/schemas/profile.py` (`CvUploadResponse`), `backend/app/schemas/jobs.py`
  (`JobStatusResponse`), `backend/app/ingestion/profile.py::ProfileSchema`,
  `backend/app/api/profile.py`, `backend/app/api/jobs.py`.

## Constraints / non-goals
- No backend changes — this task only consumes the already-implemented P5-04/05/06 endpoints. If
  you find the backend contract is genuinely unusable from the frontend, say so explicitly rather
  than quietly reshaping backend files (that would need its own task/review).
- No PDP generation UI — P7.
- No dashboard UI — P8.
- Keep styling consistent with the existing minimal styling approach in `components/Chat.tsx` /
  `app/globals.css` — no new UI framework/dependency without strong justification.
