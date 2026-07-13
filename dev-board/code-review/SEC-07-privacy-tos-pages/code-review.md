# Code review — SEC-07-privacy-tos-pages · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend/app/privacy/page.tsx:77-80 | Redaction is stated in present-tense fact ("your contact details **are** redacted … **are** stripped out at the boundary") while the actual chokepoint (SEC-08/S10) is still `pending` in queue.md — so today no redaction happens. Task explicitly permits describing the intended/contracted behaviour and this uses the sanctioned "before it is sent" framing without naming a shipped mechanism, so it is within bounds — but the present-tense phrasing slightly overstates current reality. | Optional: when SEC-08 lands, no change needed; until then consider a light hedge (e.g. "are designed to be redacted"). Not gating — the task authorized contracted-behaviour wording. |
| C2 | nit | frontend/lib/policy.ts:14 vs backend/app/config.py:155 | Version sync is a hand-maintained shared literal (`"2026-07-13"` in both). Cross-reference comment + "bump BOTH" rule documented; acceptable per KISS/no-new-API constraint, but there is no automated guard against drift. | None required. If drift risk grows, a later task could add a build-time assertion; out of scope here. |

## Notes
- **Acceptance criteria — all met.** Verified directly:
  - `/privacy` + `/terms` are static server components; no `middleware.ts`, `layout.tsx` has no auth/`fetchSession`/redirect, BFF proxy scoped to `/api/*` only → reachable unauthenticated, no redirect loop.
  - Login consent checkbox links resolve: `Login.tsx:103` → `/terms`, `:107` → `/privacy` (both plain `<a href>`, public).
  - Privacy notice covers: CV→third-party LLM with contact redaction (name/email/phone/address/links/photo stripped, professional history kept), retention ≤30d SSO / session-only guest, data-may-be-lost/no-backups, `GET /api/me/export`, `DELETE /api/me`, SSO-only/no-passwords, self-hosted Postgres/Redis, GDPR rights list, learned-prefs as "may in future" (P9 unchecked — correct).
  - ToS covers scope (coaching/personal-dev; **not** job board, **not** medical/legal/financial/therapeutic), no-warranty, termination, privacy pointer.
  - Version shown on both pages via shared `LegalPage` header; `POLICY_VERSION` == backend `CONSENT_POLICY_VERSION` default (`2026-07-13`) — confirmed in source.
- **Tests:** ran `npx jest legalPages` → 12/12 pass. Assertions pin each required disclosure phrase and the version; the bare `render()` with nothing mocked is itself the unauthenticated-render guarantee. Good coverage for a content task.
- **DRY/SoC/KISS:** shared `LegalPage` shell keeps the two pages DRY and styling consistent with `app/profile/page.tsx` conventions (`mx-auto max-w-3xl`, Tailwind). No backend surface added, per constraint. No secrets, no security surface (static content, no untrusted input, no data fetching).
- SEC-08 status independently confirmed `pending` in queue.md — the "before it is sent" phrasing choice is justified and honest about the not-yet-shipped mechanism.
