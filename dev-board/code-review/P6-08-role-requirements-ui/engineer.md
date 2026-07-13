# Engineer report — P6-08-role-requirements-ui · Revision 1

## Summary
Added the `/roles` market-requirements surface (design §5.6 / §9): a target-role search that renders
the role's **frequency-ranked, cited** requirements and — for a logged-in user — a **read-only skills
gap**. Explicitly not a job board (§1.1): no listings, no apply, no save/track. Mirrors the
`app/profile` route + `lib/profile` conventions exactly; the cold-role `202` case reuses
`pollJobUntilTerminal` from `lib/profile.ts` (not reimplemented). Consumes P6-07's endpoints verbatim
via the same-origin BFF proxy — no backend changes.

## Files changed
New:
- `frontend/lib/roles.ts` — API client mirroring `lib/profile.ts`: pure functions w/ injectable
  `fetchImpl`/`baseUrl`, wire types verbatim to `app/schemas/roles.py` + `skills_gap.py` (snake_case),
  typed `RolesApiError`, defensive parsers, discriminated `RoleRequirementsOutcome`/`RoleGapOutcome`
  (`{kind:"requirements"|"gap"}` vs `{kind:"mining",taskId}` for 202). Re-exports
  `pollJobUntilTerminal`/`JobStatus`/`isAbortError` from `lib/profile.ts` (reuse, no second poller).
- `frontend/components/RoleRequirements.tsx` — presentational component: role input + submit, ranked
  cited requirement list, cold-mine progress→poll→re-fetch, guest login-prompt vs. user gap panel
  (incl. `profile_missing` → "upload a CV" and cold `role_profile_missing` → poll).
- `frontend/app/roles/page.tsx` — App Router route; session hydration via `fetchSession()`, Login gate,
  header/`Link` nav (Back to chat) — structural clone of `app/profile/page.tsx`.
- `frontend/lib/url.ts` — extracted the `safeHttpUrl` XSS guard (see key decisions).
- `frontend/__tests__/roles.test.ts`, `frontend/__tests__/RoleRequirements.test.tsx`.

Modified:
- `frontend/components/Chat.tsx` — added `/roles` nav `Link` in the header (mirrors `/profile`); now
  imports `safeHttpUrl` from `lib/url` instead of its local copy.

## Key decisions
- **`safeHttpUrl` extracted to `lib/url.ts` (DRY/SoC).** Role evidence URLs are untrusted crawled
  content — the exact DOM-XSS-sink case Chat's citation renderer already guarded. Rather than
  duplicate the security helper, I moved the one audited definition to `lib/url.ts` and pointed both
  Chat citations and role evidence at it. Pure function, no behavior change (Chat.test still green).
- **Wire types snake_case, verbatim to backend schemas** (task: "matching the backend schemas
  verbatim"), unlike the camelCase `JobStatus` — roles data is read-only display, no round-trip, so
  keeping `evidence_count`/`refreshed_at` as-is avoids a lossy remap.
- **Guest gap gating** (§5.6): the component checks `session.role` and simply never calls `/gap` for a
  guest (it would 403), showing a plain "log in" prompt — no silent 403/empty state. `/gap` 403 fallback
  still exists in the client for defense.
- **Session gate mirrors `app/profile`**: an unauthenticated visitor (no session cookie) sees `Login`
  (which mints a guest session), so the rate-limited `/requirements` call always has a session key; a
  `guest` session then browses requirements. Guest-vs-user is the `session.role` distinction inside.
- **Cold-role 202 → transparent poll+re-fetch loop** reusing `pollJobUntilTerminal`, `AbortController`
  on unmount/new-submit (mirrors `CvUpload`). A `failure` terminal surfaces the client-safe error.
- **Citations always rendered per requirement** (evidence links / count, `evidence_count`, staleness
  from `refreshed_at`) — the "cited, frequency-ranked" exit criterion, never a bare skill list.

## How to verify
- `cd frontend && npm run type-check && npm run lint && npm test`
- Manual: chat header → **Roles** → search a role → ranked cited list; as a guest see the login prompt,
  as a user see the gap; a never-mined role shows the "gathering market data…" state then resolves.

## Tests (final step — mandatory)
- `npm run type-check` → clean (tsc `--noEmit`, no errors).
- `npm run lint` → ✔ No ESLint warnings or errors (fixed one `react/no-unescaped-entities` apostrophe).
- `npm test` → **16 suites, 151 tests passed** (2 new suites: `roles.test.ts`, `RoleRequirements.test.tsx`;
  `Chat.test.tsx` still green after the `safeHttpUrl` extraction + nav link). No failures.
- New tests cover: requirements render (ranked + cited link), cold-mine poll→resolved render,
  guest (login prompt, `/gap` never called) vs. user gap, `profile_missing` prompt, and a 429 API-error
  state; plus lib-level parse/202/403/malformed-handle cases.

## Self-check
- [x] Meets acceptance criteria: guest+user render; cold 202 poll→resolve w/o reload; citations per
  requirement; no listings/apply/save/track; component+unit tests; eslint+tsc+jest green.
- [x] No secrets; layering respected (thin `lib/` client → same-origin BFF proxy, no direct backend URL,
  no client Authorization); no backend changes.
- [x] Tests/lints pass (pasted above).
