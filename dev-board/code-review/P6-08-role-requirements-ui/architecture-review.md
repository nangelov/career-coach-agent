# Architecture review — P6-08-role-requirements-ui · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 FE structure | route in `app/`, presentational in `components/`, DI API client in `lib/` | `app/roles/page.tsx` (route+session gate), `components/RoleRequirements.tsx` (presentational), `lib/roles.ts` (pure fns, injectable `fetchImpl`/`baseUrl`) — mirrors `app/profile` + `lib/profile` exactly | none |
| A2 | §7.2/SEC-04 BFF posture | same-origin only, no direct backend URL, no client-side Authorization | `baseUrl=""` → `/api` proxy, `credentials:"same-origin"`, token injected server-side; no `Authorization` in client | none |
| A3 | Wire types verbatim | mirror `schemas/roles.py` + `schemas/skills_gap.py` (snake_case) | `RoleRequirement`/`RoleRequirements`/`SkillGap`/`SkillsGap`/`SkillsGapStatus` field-for-field match backend (`evidence_count`, `refreshed_at`, `matched`, `gap`, `status`); 202 `task_id` handle matches `RoleMiningAccepted` | none |
| A4 | §5.6 guest-vs-user contract | guest browses requirements (no auth); `/gap` gated, guest gets prompt not silent 403 | `/requirements` called for all sessions; `/gap` never called for `session.role==="guest"`, shows "log in" prompt; `profile_missing` → "upload a CV" prompt | none |
| A5 | Reuse generic poller (no second poller) | reuse `pollJobUntilTerminal`/`JobStatus` from `lib/profile.ts` for the 202 cold-mine case | re-exported (not reimplemented); `resolveRequirements`/`resolveGap` poll → re-fetch loop with `AbortController` | none |
| A6 | §1.1 not a job board | no listings, no apply, no save/track UI anywhere | component renders only ranked+cited requirement list + read-only gap; no inventory/apply/track affordances | none |
| A7 | §5.6 cited-requirements exit criterion | every requirement carries citations, frequency-ranked | `Citations`/`EvidenceLink` per requirement + gap item; `evidence_count`/`refreshed_at` staleness surfaced; frequency % shown | none |
| A8 | DRY/SoC | avoid duplicating the untrusted-URL XSS guard | `safeHttpUrl` extracted to `lib/url.ts`, shared by Chat citations + role evidence — one audited definition | none (improvement) |

## Cross-cutting checks
- [x] Fits target structure (§8) + FE layering (app/ route → components/ presentational → lib/ DI client)
- [x] Honors locked decisions (SSO/guest session via httpOnly cookie; same-origin BFF; no backend changes; untrusted-URL guard preserved)
- [x] Interfaces-before-implementations honored (typed `RolesApiError`, discriminated `Role*Outcome`, injectable `fetchImpl`/`baseUrl` — the profile-client seam pattern)
- [x] Budget posture respected (no paid deps; frontend-only)

## Notes
- The `safeHttpUrl` extraction into `lib/url.ts` also rewrites `components/Chat.tsx` (broadens the diff beyond the new route). It is a pure refactor with no behavior change and `Chat.test` green — accepted, and the right DRY call rather than a duplicated security helper.
- `lib/roles.ts` depends on `lib/profile.ts` for the shared poller/`JobStatus`/`isAbortError`. Consistent with blessed FE layering (both are `lib/` clients; `profile` owns the generic async-job seam). No follow-up needed; if a third consumer appears, consider lifting the poller to a neutral `lib/jobs.ts`, but YAGNI for now.
- Phase fit: read-only gap display only, no PDP wiring — correctly defers coupling to P7.
