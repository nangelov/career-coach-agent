# Engineer report — P11-03-ga4-analytics · Revision 1

## Summary
Reintroduced Google Analytics 4 (`gtag.js`) in the v2 Next.js App Router frontend (design §6.27 / §7.8):
pageviews plus non-content engagement events, ported from the v1 `window.gtag?.(...)` pattern. GA is
env-gated (`NEXT_PUBLIC_GA_MEASUREMENT_ID`) and consent-gated — the script loads only once an active
`Session` exists (the §6.22 gate is already satisfied server-side to obtain a session), never on the
pre-login screen. Event parameters carry only metadata (roles, ratings, booleans, item-type enums, UUID
ids) with a runtime backstop that strips free-text-shaped values. CSP was minimally widened for GA's two
Google origins only.

## Files changed
- `lib/analytics.ts` — new. Env-read `GA_MEASUREMENT_ID`, `isAnalyticsEnabled()`, typed `AnalyticsEvent`
  union, `trackEvent`/`trackPageview` (SSR-safe, `window.gtag?.(...)`), and `sanitizeParams` (drops
  `undefined` + any string over `MAX_PARAM_STRING_LEN` = 64 → the PII backstop).
- `components/Analytics.tsx` — new. Root-layout client component; self-hydrates the session via
  `fetchSession()`, injects `gtag.js` (`next/script`, `afterInteractive`) + a `gtag('config', ...)` only
  when enabled AND a session is present; fires pageviews on App Router route changes via `usePathname`
  (skips the first run — `config` sends the initial pageview).
- `app/layout.tsx` — renders `<Analytics />` once so it covers every route.
- `next.config.ts` — CSP: added `https://www.googletagmanager.com` to `script-src`; added
  `googletagmanager.com` + `google-analytics.com` (+ `*.google-analytics.com`, `*.analytics.google.com`)
  to `connect-src`. Everything else (`object-src 'none'`, `frame-ancestors 'none'`, etc.) unchanged.
- `components/Chat.tsx` — `send_message` (metadata: `role`), `stop_generation`, `message_feedback`
  (`rating`, `has_reason`).
- `components/CvUpload.tsx` — `upload_cv` (`role`, `file_type` mime).
- `components/PdpGenerator.tsx` — `generate_pdp` (`has_target_date`, `has_context` booleans).
- `components/Dashboard.tsx` — `dashboard_goal_create`.
- `components/dashboard/GoalCard.tsx` — `dashboard_proposal_approve` / `dashboard_proposal_reject` /
  `dashboard_item_create`, each with an `item_type` enum only (goal/milestone/task).
- `__tests__/analytics.test.ts`, `__tests__/Analytics.test.tsx` — new tests (see below).

## Key decisions
- **`next/script` + manual `gtag`, not `@next/third-parties`** — the latter isn't installed and adding a
  dependency conflicts with the lightweight/OSS posture (§11); `next/script` ships with Next and the manual
  wrapper preserves the v1 optional-chaining safety pattern the task calls for.
- **Single `<Analytics>` in the root layout** (DRY) rather than per-page wiring. It self-hydrates the
  session, so the "load only once a session exists" gate (§6.22 / SEC-06) holds on every route from one
  place. Cost: one extra same-origin `GET /api/auth/session` — cheap and cache-friendly.
- **Runtime PII backstop** (`sanitizeParams`): types alone don't stop a future dev passing raw content, so
  string params over 64 chars are dropped before reaching `gtag` (UUID/role/rating/mime/path all fit).
- **Path-only pageviews** (no `useSearchParams`) — avoids forcing a Suspense boundary at build; sufficient
  for the engagement metrics this phase needs.
- **submit-feedback mapping:** v2 has no v1-style contact feedback form; per the task note the equivalent is
  the P9 message 👍/👎, wired as the `message_feedback` event.

## How to verify
- Unset `NEXT_PUBLIC_GA_MEASUREMENT_ID` → no script tag, no `window.gtag`, no GA network calls (the loader
  renders null and never calls `fetchSession`).
- Set it + view the pre-login screen (no session) → no script injected.
- Set it + sign in / start a guest session → `gtag.js` loads, a pageview fires, and each listed button fires
  its named event. Confirm in DevTools that event params contain no message/CV text.

## Tests (final step — mandatory)
- `npx tsc --noEmit` → clean (exit 0).
- `npm run lint` → `✔ No ESLint warnings or errors`.
- `npm test` → **25 suites / 223 tests passed**, including new `analytics.test.ts` (disabled no-op; enabled
  event forwards sanitized params; free-text param scrubbed; `gtag`-undefined safety) and
  `Analytics.test.tsx` (no script when disabled / no session; script injected once a session is present).
- No failures; nothing weakened or skipped.

## Self-check
- [x] Meets acceptance criteria (env-gated disable, session-gated load, per-action events, PII-guard test,
      minimal CSP, lint/tsc/test green).
- [x] No secrets committed (Measurement ID via `NEXT_PUBLIC_*` env only); frontend-only, no backend/layering
      changes.
- [x] Tests/lints pass (output above).
