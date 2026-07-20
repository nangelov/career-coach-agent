# Task P11-03-ga4-analytics — Reintroduce Google Analytics 4
- **Phase:** P11   **Status:** ENG   **Tags:** (F)

## Scope
tasks.md P11 item 6: **(F)** Reintroduce **Google Analytics 4** (`gtag.js`) in the Next.js frontend: pageviews
+ button-click engagement events (send-message, stop, upload-cv, generate-pdp, submit-feedback, thumbs
up/down, dashboard actions) — mirrors the v1 `ChatBot.tsx` / `PDPDialog.tsx` pattern (see
`legacy-code/frontend/src/components/ChatBot.tsx` for the shape of `window.gtag('event', ...)` calls, e.g.
`click-send-message`, `click-send-feedback` — same idea, more event types, ported to the v2 App Router
structure). Measurement ID via env; loads only after the consent gate (§6.22); **event payloads never carry
message content, CV text, or PII.**

- **Loading gate:** GA4 must not load/fire before consent. The v2 consent model (§6.22, `SEC-06`) is a
  one-time gate at session creation (guest-session start / SSO login), not an ongoing client-side flag — so
  "after the consent gate" means: **once an active `Session` exists** (see `frontend/components/Chat.tsx`,
  `session` state hydrated via `fetchSession()` from `lib/auth.ts` — non-null `session` implies consent was
  already accepted server-side to obtain it, for both guest and SSO). Load `gtag.js` (script injection, e.g.
  `next/script` with `strategy="afterInteractive"`) only once a session is present; never on the pre-login
  screen.
- **Env config:** `NEXT_PUBLIC_GA_MEASUREMENT_ID` (unset → GA4 fully disabled, no script injected, no
  `window.gtag` calls attempted — must not throw if called anyway, keep the v1 `window.gtag?.(...)` optional-
  chaining safety pattern).
- **CSP:** `frontend/next.config.ts` currently ships a strict `connect-src 'self'` / `script-src 'self'
  'unsafe-inline' 'unsafe-eval'` CSP with no third-party allowance. Loading `gtag.js` requires updating the CSP
  to allow Google's script + beacon domains (`https://www.googletagmanager.com`,
  `https://www.google-analytics.com`, `https://*.google-analytics.com`/`https://*.analytics.google.com` as
  applicable) — add only what GA4 needs, keep everything else locked down (`object-src 'none'`,
  `frame-ancestors 'none'` etc. unchanged). Read the existing CSP comment before touching it.
- **Event coverage** — a small `lib/analytics.ts` (or similar) helper wrapping `window.gtag('event', ...)`
  calls, wired into the existing handlers for: send-message, stop (cancel), upload-cv, generate-pdp,
  submit-feedback (contact form if it still exists — check `SEC` phase for what replaced v1's feedback path),
  thumbs up/down (message feedback, P9), dashboard actions (goal/task create/approve/reject — P8). Event
  **parameters** must be non-content metadata only (e.g. counts, booleans, ids that are not PII — a
  `message_id`/`thread_id` UUID is fine, raw text is not).
- Pageview tracking: standard GA4 `config` call (or `next/third-parties/google`'s `GoogleAnalytics` component
  if it fits the existing lightweight dependency posture better — engineer's call, document why).

## Acceptance criteria
- [ ] `NEXT_PUBLIC_GA_MEASUREMENT_ID` unset → zero GA4 network calls, no script tag injected, no console errors.
- [ ] `NEXT_PUBLIC_GA_MEASUREMENT_ID` set + no session yet (pre-login/consent screen) → GA4 not loaded.
- [ ] Once a session exists (guest or SSO) → GA4 script loads, a pageview fires, and each of the listed button
      actions fires a named custom event.
- [ ] A test (unit/component, mocking `window.gtag`) asserts at least one event call's parameter object
      contains no message/CV-shaped free text (guard against a future dev accidentally passing raw content).
- [ ] CSP updated minimally for GA4 domains only; existing security headers otherwise unchanged.
- [ ] `npm run lint`, `tsc`, and `npm test` all green.

## Design references
- dev-board/app-design-and-features.md: §6.27 (Product analytics → GA4), §6.22 (consent gate)
- v1 reference pattern: `legacy-code/frontend/src/components/ChatBot.tsx` (`window.gtag(...)` calls) — port the
  *pattern*, not the code (CRA → Next.js App Router).

## Constraints / non-goals
- Not a new consent-state store — reuse the existing session-presence signal; don't add a second consent
  mechanism.
- No server-side/backend changes — this is frontend-only. If a "submit-feedback" click handler doesn't exist
  in v2 yet under that name, use whatever the equivalent v2 feedback action is (message 👍/👎 from P9) and note
  the mapping in your report.
- Don't touch `P11-01`/`P11-02` (backend OTel/Sentry) — separate concerns.
