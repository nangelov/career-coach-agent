# Architecture review — P7-04-frontend-pdp-ui · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure (frontend layout) | client in `lib/`, UI in `components/`, thin route in `app/` | `lib/pdp.ts` (client), `components/PdpGenerator.tsx` (UI), `app/pdp/page.tsx` (route) — exact split blessed for P1-08/roles/profile | none |
| A2 | Transport layering (SEC-04 / §7.2) | same-origin BFF proxy, relative `/api/...`, `credentials: "same-origin"`, token never client-side | `POST /api/pdp`, `credentials: "same-origin"`, no `Authorization` set client-side; BFF injects it server-side; DOM isolated to `triggerDownload` | none |
| A3 | Backend contract fidelity (P7-03) | request `career_goal`/`target_date`/`additional_context`; 200 PDF + `X-PDP-Status`; 401/403/422/429/502 | snake_case body mapping, optional-field omission, `X-PDP-Status` narrowed to `ok`\|`role_profile_missing` on 200 (`generation_failed`→502, `profile_missing`→422 correctly attributed to non-200) | none |
| A4 | Interface-before-impl / DI seam | injectable `fetchImpl`/`baseUrl`, typed error carrying status (mirror `lib/roles.ts`) | `PdpClientOptions` DI, `PdpApiError` with `status`, pure `generatePdp` + separated `triggerDownload` — fetch path DOM-free/testable | none |
| A5 | Guest posture (§6.2 SSO-only; P7-03 403) | guest sees sign-in gate, not a broken form; session carries over | `GuestGate` reuses `upgradeGuestToSso`→`beginSsoLogin` fallback (no duplicated auth); form hidden for `role==="guest"` | none |
| A6 | Phase fit (P7, no P8 coupling) | PDP download only; no dashboard goal/task seeding | no seeding logic; success is download + status notice only | none |
| A7 | Product scope (§1.1 not a job board) | role-missing notice links to Roles/Profile, no listings/apply | inline notices link `/roles` + `/profile`; no job-board surface | none |
| A8 | BFF proxy untouched (constraint) | verify binary passthrough before editing `app/api/[...path]/route.ts` | engineer confirmed passthrough (streams body, strips only encoding/length/transfer/connection); no proxy change | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — `lib/` transport, `components/` UI, thin `app/` route; matches P1-08 blessed frontend pattern.
- [x] Honors locked decisions — SSO-only auth flow reused via `lib/auth`; BFF cookie transport (SEC-04). Backend-only locks (no ReAct parser, Postgres+Redis, in-process embeddings) are N/A to this frontend task.
- [x] Interfaces-before-implementations — injectable `fetchImpl`/`baseUrl`, typed `PdpApiError`, DOM helper isolated.
- [x] Budget posture — no new paid deps; browser-native download (object URL); no analytics vendor added.

## Notes
- GA4 correctly deferred: engineer grepped `frontend/` and found no existing analytics; per task it added none (P11 owns GA4 reintroduction). Consistent with the observability ruling that GA4 is a P11 concern — logged follow-up, not a gap.
- Optional `target_date` (v1 required it) is a deliberate, task-sanctioned relaxation, not a deviation.
- `generateFallback` retains a 403 branch as defensive depth even though the guest gate makes 403 unreachable from the form — harmless, keeps the status→message map total.
- Filename `Content-Disposition` parsing / UTF-8 decoding is correctness, not design conformance — deferred to the code-reviewer.
