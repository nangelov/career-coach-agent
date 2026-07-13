# Task P6-08-role-requirements-ui — Role-requirements frontend page
- **Phase:** P6   **Status:** ENG   **Tags:** (F)
## Scope
tasks.md P6 bullet 12: Role-requirements UI: target role, frequency-ranked skills **with citations**, gap vs
profile. **No listings, no apply, no save/track.**

Add a new Next.js App Router route (e.g. `frontend/app/roles/page.tsx`, following the `frontend/app/
profile/page.tsx` structure/conventions exactly — session hydration via `fetchSession()`/`lib/auth.ts`, the
same header/`Link` nav pattern, `"use client"`) plus a `frontend/components/RoleRequirements.tsx` presentational
component and a `frontend/lib/roles.ts` API-client module mirroring `lib/profile.ts`'s conventions (pure
functions, injectable `fetchImpl`/`baseUrl`, wire types matching the backend schemas verbatim, a typed
`RolesApiError`, and **reuse `pollJobUntilTerminal` / the `JobStatus` polling shape from `lib/profile.ts`** for
the `202` cold-mine-in-progress case — do not reimplement polling).

**Backend contract already shipped (P6-07, DONE) — read its `engineer.md` for exact field names:**
- `GET /api/roles/{role}/requirements` — **no auth required** (guests can use this, design §5.6). `200` with
  ranked+cited requirements, or `202` + a `task_id` (same shape as `CvUploadResponse`) while a role is being
  mined for the first time.
- `GET /api/roles/{role}/gap` — **requires auth** (`403` for a guest, mirrors the existing profile-edit
  guest-rejection UX already handled elsewhere in the app). `200` with matched/gap skills, or a
  `profile_missing`/`role_profile_missing` status per P6-07's `SkillsGapResult` contract, or `202` + `task_id`
  on a cold role.

**UI behavior:**
1. A text input for the target role (e.g. "AI Solution Architect") + submit.
2. On submit, call `GET /api/roles/{role}/requirements` (via the Next.js BFF proxy, same-origin — no direct
   backend calls, per the existing SEC-04 BFF posture every other `lib/*.ts` module already follows).
   - `200`: render the frequency-ranked skill list, each with its citation(s)/evidence (source links/count),
     `evidence_count`, and a staleness note if useful (`refreshed_at`).
   - `202`: show a "we're gathering market data for this role for the first time…" progress state and poll
     `GET /api/jobs/status/{task_id}` (via `pollJobUntilTerminal`) until it resolves, then re-fetch
     `/requirements`.
3. If the user is logged in (session from `fetchSession()`), also call `GET /api/roles/{role}/gap` and render
   the **gap** — which of the ranked requirements the user's profile is missing — inline or as a second panel.
   If the user is a guest, show a plain "log in to see your personal skills gap" prompt instead of calling
   `/gap` at all (no point hitting a route that will 403).
4. **No listings, no apply/save/track UI anywhere on this page** — this is explicitly not a job board (§1.1);
   only the ranked requirement list + citations + gap.
5. Add a nav link to `/roles` from the chat header (mirror the existing `/profile` `Link`, `components/
   Chat.tsx` around its `<header>`).

## Acceptance criteria
- [ ] `/roles` route renders for both guests and logged-in users; guests see requirements but not a personal
      gap (with a clear "log in" prompt, not a silent 403/empty state).
- [ ] Cold-role (`202`) flow shows progress and resolves to the rendered requirements without a page reload,
      reusing `pollJobUntilTerminal`.
- [ ] Citations/evidence are visibly rendered per requirement (not just a bare skill list) — this is the
      "cited, frequency-ranked" contract from the design's exit criterion.
- [ ] No listings/apply/save/track UI element exists anywhere in the new component(s).
- [ ] Component/unit tests (Jest, mirroring existing `frontend/**/*.test.tsx` conventions if present, or the
      pattern used for `CvUpload`/`ProfileView`) cover: requirements render, cold-mine polling → resolved
      render, guest vs. logged-in gap behavior, and an API-error state.
- [ ] `eslint` + `tsc` + `jest` all pass.

## Design references
- dev-board/plan.md: Phase 6, bullet 9 (UI mention in exit criteria)  ·  dev-board/app-design-and-features.md
  §5.6, §1.1 (scope — no job board), §9 API table
- Reuse: `frontend/app/profile/page.tsx`, `frontend/components/CvUpload.tsx` / `ProfileView.tsx`,
  `frontend/lib/profile.ts` (`pollJobUntilTerminal`, `JobStatus`, error-class pattern), `frontend/lib/auth.ts`
  (`fetchSession`), the BFF proxy (`frontend/app/api/[...path]/route.ts` — same-origin calls only, no direct
  backend URL)

## Constraints / non-goals
- No backend changes — P6-07's endpoints are already shipped and DONE; if you find the contract doesn't match
  what's needed, work around it in the client layer rather than modifying the backend (flag a mismatch in your
  report if truly blocking).
- No PDP integration here (P7) — the gap shown here is read-only display, not wired into PDP generation yet.
