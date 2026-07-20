# Code review — P11-03-ga4-analytics · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | components/Analytics.tsx:35 | `fetchSession().then(...)` has no `.catch()`. `fetchSession` swallows network errors (returns null), but a 200 with malformed JSON would reject `response.json()` → unhandled promise rejection. Very unlikely from the same-origin BFF. | Optionally chain `.catch(() => {})` (or `.then(next, () => {})`) for defense in depth. Non-blocking. |
| C2 | nit | lib/analytics.ts:102-107 | `trackPageview` writes `page_path` straight to `gtag`, bypassing `sanitizeParams`, so a long path is not length-capped. Paths are not PII, so this is acceptable and intentional — noted only for completeness. | None required. |

## Notes
- **Acceptance criteria all met and verified:**
  - Env gate: `GA_MEASUREMENT_ID` read once; `isAnalyticsEnabled()` short-circuits `trackEvent`/`trackPageview` and `<Analytics>` renders null + never calls `fetchSession` (test-covered).
  - Session gate: script injected only when `session` is non-null AND enabled; pre-login (session null) injects nothing (test-covered). Interpretation (session-presence ⇒ consent) matches task.md's own spec.
  - Event coverage: send_message, stop_generation, upload_cv, generate_pdp, message_feedback (P9 👍/👎 — correctly mapped as the v2 equivalent of v1 submit-feedback), dashboard goal/item create + proposal approve/reject. All params are non-content metadata (role, mime, booleans, item-type enum, rating).
  - PII backstop: `sanitizeParams` drops `undefined` and strings > 64 chars; UUID/role/rating/mime all fit. Directly unit-tested with simulated free-text leakage assertions.
  - CSP: minimally widened — `googletagmanager.com` added to `script-src`; GA beacon origins to `connect-src`; all other directives (`object-src 'none'`, `frame-ancestors 'none'`, etc.) unchanged. GA4's `region1.google-analytics.com` beacon is covered by `*.google-analytics.com`; image-pixel fallback is covered by existing `img-src https:`.
  - `gtag` optional-chaining safety preserved (`window.gtag?.(...)`); test asserts no throw when `gtag` is undefined.
- **Correctness:** pageview de-dup via `initialPageviewHandled` ref is sound — the `gtag('config')` call emits the initial pageview, the first effect run after session load is skipped, subsequent `usePathname` changes fire `trackPageview`. No duplicate, no missed navigations.
- **Hooks:** `CvUpload` `useCallback` deps correctly extended with `session.role`; no stale-closure or missing-dep issues elsewhere.
- **Security:** no secrets committed (Measurement ID is a public `NEXT_PUBLIC_*` value); frontend-only, no backend/layering changes.
- Ran the two new suites locally: 2 passed / 7 tests. Consistent with engineer's reported full-suite green (25 suites / 223 tests), tsc, and lint.
