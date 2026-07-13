# Code review — P6-08-role-requirements-ui · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | minor | frontend/components/RoleRequirements.tsx:170,207 | `reqBusy` (hence the submit button) re-enables once *requirements* resolve while the *gap* panel is still loading. A resubmit in that window aborts the previous `AbortController`, but the in-flight `getRoleGap` fetch itself is not cancelled (the client fetches don't accept a signal — only `pollJobUntilTerminal` does), so a stale gap from the prior role can be set after the new search starts. Worst case is a briefly-mismatched gap panel; `GapSection` only renders when `reqPhase==="ready"`, which masks most of it. | Optionally keep the button disabled while `gapPhase` is loading/mining too, or track a per-submit token/generation to drop stale gap results. Not gating. |
| C2 | nit | frontend/components/RoleRequirements.tsx:409-421 | `GapSection` has no explicit branch for `gap.status === "role_profile_missing"`; a 200 body with that status (gap=null) would fall through to `GapPanel` → the celebratory "You already have every ranked requirement 🎉". This is currently unreachable — the backend returns `role_profile_missing` as a **202** (mine handle), which the poll loop already handles — so it's a latent defensive gap only. | Optionally guard `GapPanel` on `gap.status === "ok"` (or handle the missing-status explicitly) so a future contract change can't render "you have everything" for a null gap. |

## Notes
- Verified locally: `npm run type-check` clean, `npm run lint` clean, and the 3 affected suites (`roles.test.ts`, `RoleRequirements.test.tsx`, `Chat.test.tsx`) → 28/28 pass.
- Wire types in `lib/roles.ts` match `app/schemas/roles.py` + `app/schemas/skills_gap.py` verbatim (snake_case); parsers degrade missing/malformed fields defensively.
- Security: no client-side `Authorization` (BFF same-origin, `credentials: "same-origin"`); `role` is `encodeURIComponent`-escaped into the path; untrusted crawled evidence URLs are gated through the extracted `safeHttpUrl` (`lib/url.ts`) before becoming anchors, non-URL evidence renders as escaped text; no `dangerouslySetInnerHTML`. The `safeHttpUrl` extraction from `Chat.tsx` is a clean move (DRY), behavior-identical, Chat tests still green.
- Reuse honored: `pollJobUntilTerminal`/`JobStatus`/`isAbortError` are re-exported from `lib/profile.ts`, no second poller. Route/page mirrors `app/profile/page.tsx` conventions.
- Acceptance criteria all met: guest vs. user gap gating (guest never calls `/gap`), cold-role 202 poll→resolve without reload, per-requirement citations, no listings/apply/save/track, error state, and the mandated test coverage.
