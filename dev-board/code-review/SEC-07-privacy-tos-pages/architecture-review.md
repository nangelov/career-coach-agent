# Architecture review — SEC-07-privacy-tos-pages · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Public reachability | Pages must render before any session (linked from logged-out consent checkbox) | `app/privacy/page.tsx` + `app/terms/page.tsx` are static server components; no `frontend/middleware.*` exists so no route gating; BFF proxy is `/api/*` only | none |
| A2 | Login link resolution (§6.22) | Consent checkbox links to `/terms` + `/privacy` | `Login.tsx` lines 103/107 link to exactly those paths; `LegalPage` cross-links siblings + back to `/` | none |
| A3 | CV redaction disclosure (§6.16) | Contact details (name/email/phone/postal/links) stripped before external inference; employers/titles/dates/skills/education kept; disclosed to user; SEC-08 mechanism not yet merged | Privacy page states redaction "before it is sent" (name/email/phone/address/links/photo), keeps professional history; phrased as intent not shipped mechanism (queue.md SEC-08 pending). Photo is an extra field beyond §6.16 list — accurate superset, not a conflict | none |
| A4 | Data-loss disclosure (§6.17) | Data may be lost on restart; no backups; retention is a max not a guarantee | "Data may be lost" section states exactly this | none |
| A5 | Retention (§6.18) | SSO 30d after last activity; guests session-only; `DELETE /api/me` immediate | Retention section covers all three | none |
| A6 | GDPR rights (§7.6) | Access/export (`GET /api/me/export`), erasure (`DELETE /api/me`, cascading), rectification/restriction/objection/withdraw-consent, complaint right, controller identity, legal basis = consent | All present; SSO-only/no-passwords, self-hosted PG/Redis (no managed tier) stated as fact per SEC-05 | none |
| A7 | Consent gate not self-gated (§6.22) | Pages readable before accepting (no chicken-and-egg) | No consent gate on the pages; references the gate without enforcing it | none |
| A8 | Product scope (§1.1) — ToS | Coaching/personal-development; not a job board; not medical/legal/financial/therapeutic | ToS "What the app is / is not" mirrors §1.1 verbatim incl. redirect-not-refuse framing; no-warranty + termination present | none |
| A9 | Policy version sync (§6.22/§7.6) | Visible version consistent with `settings.CONSENT_POLICY_VERSION` | `lib/policy.ts` `POLICY_VERSION="2026-07-13"` == backend default; header renders version + last-updated; "bump both" rule documented | none |
| A10 | Learned-memory hedging (P9) | Not shipped yet — must not overclaim | Phrased "may in future ... you will be able to view and delete these", consistent with unchecked P9 and [[project-v2-locked-stack]] decision #8 | none |

## Cross-cutting checks
- [x] Fits target structure (§8) — content + two static Next routes under `frontend/app/`, shared shell in `components/`, constants in `lib/`; no backend logic added (per constraint)
- [x] Honors locked decisions — SSO-only/no-passwords, self-hosted Postgres+Redis (no managed tier) stated as fact; no new API surface invented
- [x] Interfaces-before-implementations — N/A (static content); version sync via shared literal + cross-ref comment rather than a premature config endpoint (KISS/YAGNI)
- [x] Budget posture respected — no new infrastructure

## Notes
- Version-sync as a hardcoded literal is acceptable here: text + version change together in one commit, and the backend constant is the enforcement source of truth. Logged as a design ruling — the frontend copy is display-only; the consent gate remains backed by `CONSENT_POLICY_VERSION`. Follow-up (non-blocking): if the policy text and version ever diverge across commits, revisit exposing the version via the existing session plumbing.
- Photo added to the redaction list beyond the §6.16 enumeration is a truthful superset (task explicitly asked for it) and does not conflict with the design.
