# Architecture review — P11-03-ga4-analytics · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 FE structure | DOM-light DI/helper logic in `lib/`, React in `components/` | `lib/analytics.ts` (pure wrapper) + `components/Analytics.tsx` (client loader) — correct split | none |
| A2 | §6.27 GA4 scope | pageviews + button-click engagement events, no PII | pageview via `config` + route-change `page_view`; 9 named events (send/stop/upload/pdp/feedback/dashboard) with metadata-only params (role, rating, booleans, item_type enum, mime) | none |
| A3 | §6.22 / SEC-06 consent gate | GA loads only after consent; no second consent store | Load gated on non-null `Session`; §6.22 confirms no session is minted without ToS/privacy acceptance, so session-presence = consent. No new consent mechanism added | none — reuse of session signal is exactly the design intent |
| A4 | §6.27 no-PII payloads | payloads never carry message/CV text | Closed `AnalyticsEvent` union + `sanitizeParams` runtime backstop (drops undefined + strings >64 chars); all call sites pass enums/booleans/ids only | none |
| A5 | §7.2 / §7.8 CSP posture | minimal third-party widening, everything else locked | `script-src`/`connect-src` widened to GA origins only; `object-src 'none'`, `frame-ancestors 'none'`, `base-uri`, `form-action` unchanged; comment updated | none |
| A6 | env gating | unset `NEXT_PUBLIC_GA_MEASUREMENT_ID` → fully disabled | `isAnalyticsEnabled()` master switch; component renders null, no script, no `fetchSession`, SSR-safe `window.gtag?.()` | none |
| A7 | §11 budget posture | free / OSS, no needless deps | `next/script` (ships with Next); rejected `@next/third-parties` to avoid a new dep — documented | none |
| A8 | phase fit / non-goals | frontend-only, no backend/layering changes; don't touch P11-01/02 | changes confined to `lib/`, `components/`, `app/layout.tsx`, `next.config.ts` | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + FE layering (lib helper vs component) — matches blessed FE structure ruling
- [x] Honors locked decisions (SSO/guest session model reused as consent signal; no backend change; no new store)
- [x] Interfaces-before-implementations — thin typed wrapper, no leakage into product handlers beyond one-line calls
- [x] Budget posture respected (free GA4, no new npm dependency)

## Notes
- Minor / logged follow-up (not blocking): `Analytics.tsx` self-hydrates via its own `fetchSession()`, one extra
  same-origin `GET /api/auth/session` that duplicates the pages' session fetch. Engineer's DRY rationale (single
  root-layout loader) is sound; if a shared session context/provider lands later, fold this into it to drop the
  extra call. Cheap to unwind — does not gate.
- submit-feedback → `message_feedback` (P9 👍/👎) mapping is correct: v2 has no v1-style contact form (matches
  task constraint and §7.6 rescope).
- Path-only pageviews (no `useSearchParams`) is an acceptable scope call for engagement metrics this phase.
