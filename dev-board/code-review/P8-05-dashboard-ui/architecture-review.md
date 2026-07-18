# Architecture review — P8-05-dashboard-ui · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 FE structure / layering | `lib/` = DOM-light DI API client, `components/` = React, `app/` = route | `lib/dashboard.ts` pure client (injectable `fetchImpl`/`baseUrl`, no DOM); `components/Dashboard.tsx` + `components/dashboard/GoalCard.tsx`; `app/dashboard/page.tsx` route | none |
| A2 | Wire contract (§9, backend P8-02) | wire types mirror `schemas/dashboard.py` verbatim (snake_case); paths match router | Types, fields, and endpoint paths (`/api/dashboard`, `/goals`, `/goals/{id}/milestones`, `/milestones/{id}`, `/tasks`, `/progress`) match `api/dashboard.py` exactly; `limit`/`offset` query on progress list matches | none |
| A3 | SEC-04 / §7.2 no client auth | BFF injects `Authorization` server-side; client never touches a token | `credentials: "same-origin"` only; no token handling — mirrors `lib/roles.ts`/`lib/profile.ts` | none |
| A4 | Guest contract (§5.2 "dashboard requires an account") | guest → sign-in/upgrade prompt, not a raw 403 | `Dashboard` gates `session.role === "guest"` to `GuestGate` (SSO upgrade preserving session, mirrors `PdpGenerator`); backend `_require_user` 403 is the defense-in-depth backstop | none |
| A5 | Never-silent AI writes (§5.2, §5.5) | proposed→approve/reject; approve = PATCH off `proposed`, reject = DELETE; attribution honest | `APPROVE_STATUS` maps goal→active / milestone→pending / task→todo via generic update; reject = delete; "Proposed by your coach" badge; human writes never send `proposed` (types exclude it, server enforces `source="user"`) | none |
| A6 | §5.2 UI surface | goals/milestones/tasks board, progress/streak, % to target date, log progress | Grouped goal columns, nested rows, `ProgressPanel` (streak + activity bar), server-computed `time_progress_pct`/`task_completion_pct` bars, log-progress action | none |
| A7 | Budget / dep posture (§11) | no heavy frontend deps; plain CSS/SVG | `package.json` unchanged; plain CSS bars, no charting lib | none |
| A8 | Phase fit (Plan P8) | consume P8-02 human CRUD only; no backend/graph changes | No backend edits; does not call chat graph or P8-03 tools | none |
| A9 | Nav wiring | Dashboard link alongside Roles/Profile/Plan | Added in `components/Chat.tsx` header (the single primary-nav location; other pages carry only "Back to chat", which `app/dashboard/page.tsx` mirrors) | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (route → component → DI client; no cross-layer leak)
- [x] Honors locked decisions (SSO-only upgrade path; no client token; no new datastore/dep)
- [x] Interfaces-before-implementations (`DashboardActions` seam; injectable `fetchImpl`/`baseUrl`; typed `DashboardApiError` carrying HTTP status; defensive `raw → typed` parsers)
- [x] Budget posture respected (free/OSS; zero new dependencies)

## Notes
- Refresh-after-mutation (re-fetch the server-computed summary rather than optimistic edits) is the correct call — keeps `time_progress_pct`/streak authoritative per P8-02; blessed.
- Analytics: no GA4/`gtag` convention exists in the v2 frontend (grep clean; `lib/policy.ts` is consent-version metadata, not an interaction-event gate). The task's conditional "if the app fires interaction events" therefore does not apply — nothing invented. Correct.
- Non-blocking nit for the code-reviewer (not a design concern): `ProgressPanel`'s `day streak{... === 1 ? "" : ""}` is a no-op pluralization (both branches empty) — dead ternary.
