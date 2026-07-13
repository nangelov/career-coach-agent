# Task SEC-07-privacy-tos-pages — Privacy notice + ToS pages
- **Phase:** SEC   **Status:** ENG   **Tags:** (F/B)

## Scope
Build the actual `/privacy` and `/terms` pages the login screen already links to
(`frontend/components/Login.tsx` — added by SEC-06, currently pointing at routes that don't
exist yet). Design §6.22 / §7.6 / §6.16-18 require the notice to **state plainly**:

- **CV text is sent to a third-party LLM provider, with contact details redacted** before it
  leaves the app (name, email, phone, postal address, personal links, photo are stripped at the
  LLM egress boundary — employers/titles/dates/skills/education are kept and do leave the app,
  since that's what the coach reasons about). *Note: the actual redaction chokepoint is
  **SEC-08 (S10)**, the next task after this one — write the notice to describe the
  **intended/contracted** behavior regardless of exact landing order; if SEC-08 hasn't merged
  yet when you do this task, phrase it as "before being sent" rather than claiming a specific
  already-shipped mechanism, and don't block this task on SEC-08.*
- **Retention:** SSO accounts — 30 days after last activity, then auto-purged. Guests —
  session-only, nothing durable, ever. Either — `DELETE /api/me` for immediate erasure.
- **Data may be lost on restart** (§6.17 — free app, ephemeral hosting, no managed tier, no
  backups; retention above is a maximum, not a guarantee of availability).
- Who the data controller is, what's collected (OIDC `sub`/email/name via Google/LinkedIn login
  — no passwords ever stored; CV/profile; conversations/messages; feedback; learned
  preferences/memories once P9 ships — write this as "may in future" if that's still accurate,
  check `dev-board/tasks.md` P9 status), why (career-coaching purpose only — §1.1 scope), legal
  basis (consent), user rights (access/export via `GET /api/me/export`, erasure via
  `DELETE /api/me`, and the general GDPR rights list), and that guests get a lighter/no-storage
  path.
- ToS: acceptable use tied to the product's actual scope (§1.1 — coaching/personal development,
  explicitly **not** a job board, not medical/legal/financial advice — reuse the phrasing already
  established in `dev-board/tasks.md`'s cross-cutting definition-of-done), no warranty (free,
  hobby-scale app), account/session termination, and a pointer to the privacy notice.

## What to build
1. **Two Next.js pages**, e.g. `frontend/app/privacy/page.tsx` and `frontend/app/terms/page.tsx`
   — static content, no auth required (they must be reachable **before** login, since the
   consent checkbox links to them from the logged-out login screen). Keep the styling consistent
   with the rest of the app (reuse whatever base layout/typography conventions
   `frontend/app/` already uses).
2. **A visible policy version + "last updated" date** on both pages, matching
   `settings.CONSENT_POLICY_VERSION` (added in SEC-06, `backend/app/config.py`) so the two stay
   in sync — either hardcode the same literal with a comment cross-referencing the backend
   constant, or (cleaner) expose it via the existing `GET /api/auth/session`-style plumbing /
   a tiny public config endpoint if one already fits; use your judgment, document the choice.
3. **Content accuracy check**: before writing the CV-redaction paragraph, actually check
   whether SEC-08 (contact-detail redaction) has landed yet
   (`dev-board/code-review/queue.md`) — phrase precisely, don't overclaim a mechanism that
   isn't built, but also don't undersell what's already true today (e.g. self-hosted
   Postgres/Redis, SSO-only/no-passwords, cascading erasure from SEC-05 — all already shipped
   and can be stated as fact).
4. Confirm the Login screen's `/terms` and `/privacy` links resolve correctly (no auth
   redirect loop — these must be public routes) and that nothing in the SEC-04 BFF proxy or any
   auth middleware accidentally gates them behind a session.

## Acceptance criteria
- [ ] `/privacy` and `/terms` render without requiring a session, and are linked correctly from
      the login screen's consent checkbox.
- [ ] Privacy notice explicitly states: CV text sent to a third-party LLM provider with contact
      details redacted; retention ≤30 days (SSO) / session-only (guest); data may be lost on
      restart; how to exercise erasure (`DELETE /api/me`) and export (`GET /api/me/export`).
- [ ] ToS states the actual product scope (career coaching, not a job board, not
      medical/legal/financial advice) and basic terms (no warranty, termination).
- [ ] Both pages show a policy version consistent with `CONSENT_POLICY_VERSION`.
- [ ] Basic test coverage: the pages render, contain the required disclosure phrases, and are
      reachable unauthenticated.

## Design references
- dev-board/app-design-and-features.md §6.16 (CV redaction disclosure), §6.17 (data loss
  accepted), §6.18 (retention), §6.22 (consent), §7.6 (privacy/GDPR section overall), §1.1
  (product scope).
- dev-board/tasks.md — SEC block, item **"Privacy notice + ToS pages"** (unlabeled S-number,
  sits between S13 and S10 in the block).

## Constraints / non-goals
- This is content + two static routes, not new backend logic — avoid inventing new API
  surface unless something above genuinely requires it (e.g. exposing the policy version).
- Don't gate these pages behind the consent checkbox itself (chicken-and-egg — they must be
  readable *before* accepting).
