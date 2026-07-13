# Engineer report — SEC-07-privacy-tos-pages · Revision 1

## Summary
Built the public `/privacy` and `/terms` pages the login consent checkbox already links to
(`components/Login.tsx`). Both are static server components (no auth, no data fetching), so they
render before any session exists — there is no middleware gating page routes and the BFF proxy
only covers `/api/*`, so no redirect loop is possible. Content covers all required GDPR/scope
disclosures. A visible policy version + last-updated date is shown on both, tied to the backend
`settings.CONSENT_POLICY_VERSION`.

## Files changed
- `frontend/lib/policy.ts` — new: `POLICY_VERSION` / `POLICY_LAST_UPDATED` constants, cross-referencing `backend/app/config.py` `CONSENT_POLICY_VERSION`.
- `frontend/components/LegalPage.tsx` — new: shared shell (header with version, article typography, footer cross-links) for both legal pages (DRY).
- `frontend/app/privacy/page.tsx` — new: Privacy Notice.
- `frontend/app/terms/page.tsx` — new: Terms of Service.
- `frontend/__tests__/legalPages.test.tsx` — new: render + disclosure-phrase + version coverage.

## Key decisions
- **Policy version sync via shared literal, not a new endpoint.** The notice text and the version
  change together in one commit, so a hardcoded `POLICY_VERSION` with an explicit cross-reference
  comment to the backend constant is the simplest thing that stays correct (KISS / YAGNI; task
  constraint: don't invent new API surface). Documented the "bump both" rule in `policy.ts`.
- **CV-redaction wording is intended-behaviour, not shipped-mechanism.** Checked `queue.md`:
  SEC-08 (contact-detail redaction at LLM egress) is still `pending`. Per the task I phrase it as
  "**before it is sent**, your contact details are redacted" (name/email/phone/address/links/photo
  stripped) and state that employers/titles/dates/skills/education **are** sent — without claiming
  a live mechanism (design §6.16).
- **Facts already true stated plainly** (design §6.17/§6.18, SEC-05): self-hosted Postgres/Redis
  (no managed tier), SSO-only/no passwords, cascading erasure via `DELETE /api/me`, export via
  `GET /api/me/export`, 30-day SSO retention / session-only guests, and "data may be lost on
  restart / no backups".
- **Learned preferences phrased as "may in future."** Checked `tasks.md` P9 — learned-memory
  tasks are still unchecked, so the notice says the app *may in future* learn preferences.
- **Product scope reused verbatim from §1.1 / tasks.md scope-discipline line**: coaching + personal
  development, explicitly not a job board, not medical/legal/financial/therapeutic advice.
- **Shared `LegalPage` shell** keeps the two pages DRY and styling consistent with existing
  `app/` conventions (Tailwind, `mx-auto max-w-3xl`, gray borders — matches `app/profile/page.tsx`).

## How to verify
- `cd frontend && npx jest legalPages` — page render + all required disclosure phrases + version.
- Manually: with no session cookie, visit `/privacy` and `/terms` — both render; login consent
  links resolve to them; footer links cross-navigate and back to `/`.

## Tests (final step — mandatory)
- `npx eslint` on the 5 changed files → clean (no output).
- `npx tsc --noEmit` → clean.
- `npx jest` (full frontend suite) → **14 suites / 135 tests passed**, including the new
  `legalPages.test.tsx` (12 tests). No failures; nothing to fix.

## Self-check
- [x] Meets acceptance criteria (public render, all disclosures, scope + no-warranty/termination, version consistent, test coverage).
- [x] No secrets; no backend logic added (content + two static routes only, per constraints).
- [x] Tests/lints pass (pasted above).
