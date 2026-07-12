# Architecture review — P5-07-frontend-cv-upload · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 frontend structure (lines 377–383: `lib/` = api client/auth, `components/`, App Router) | New API-client logic in `lib/`, React in `components/`, route under `app/` | `lib/profile.ts` (thin client + poller), `components/CvUpload.tsx` + `ProfileView.tsx`, `app/profile/page.tsx` | none |
| A2 | §9 API table (`POST /api/profile/cv`, `GET/PUT /api/profile`, `GET /api/jobs/status/{task_id}`) | Consume exactly these paths/verbs | `uploadCv`→POST `/api/profile/cv`; `getProfile`/`updateProfile`→GET/PUT `/api/profile`; `pollJobStatus`→GET `/api/jobs/status/{task_id}` (URL-encoded) | none |
| A3 | Layering (Router→Service split mirrored on FE) | DOM-light transport isolated from React | `lib/profile.ts` is pure/DI (`fetchImpl`/`baseUrl`), components hold only view+state; matches `lib/auth.ts`/`lib/chatStream.ts` | none |
| A4 | Wire-contract fidelity (`ingestion/profile.py::ProfileSchema`, `schemas/jobs.py`, `schemas/profile.py`) | TS types mirror Pydantic verbatim; round-trip GET→edit→PUT lossless | `Profile`/`ExperienceItem`/`EducationItem`/`JobStatus` mirror backend snake_case exactly; defensive `parseProfile`/`parseJobStatus` mappers | none |
| A5 | §4 profile reuse (lines 146/184: "reused across chats, no re-upload") | View reads persisted profile via GET, no re-upload to view | `ProfileView` loads via `getProfile`; `reloadKey` re-fetch after parse; reload re-reads GET | none |
| A6 | §7 AuthZ / guest posture (backend contract) | Guest 200-empty GET rendered; guest PUT 403 shown as clear prompt not raw error; guest upload-once 429 | `getProfile` empty-safe; `ProfileApiError(status)` lets UI branch 403/413/415/429; guest note + 403/429 friendly messages | none |
| A7 | §5.3 async job posture ("enqueue + poll progress, don't block the turn") | Off-request-path upload; poll stage/message; no page reload | `uploadCv` returns `task_id`; `pollJobUntilTerminal` interval poll renders live `stage`/`message`; abort-on-unmount | none |
| A8 | Phase fit (P5 scope) | Structured-profile UI only; no PDP (P7) / dashboard (P8) | Only upload + view/edit; nav is a single `Link`, no nav redesign | none |
| A9 | §6.2/§7.1 SSO-only session | Reuse bearer session, no new auth path | Reuses `Session`/`authHeaders`/`loadSession` from `lib/auth.ts`; route auth-gates via `Login` like `Chat` | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (lib/ transport vs components/ view, mirrors Router→Service)
- [x] Honors locked decisions (no ReAct parser touched; no new datastore/dep; SSO-only bearer reused; no backend change)
- [x] Interfaces-before-implementations respected — consumes `DocumentParser`-backed pipeline only through the stable `/api/profile/cv` + generic `/api/jobs/status` contract; poller is job-generic (reusable by P6 crawl/OCR), not CV-coupled
- [x] Budget posture respected — no new UI framework/dependency; reuses existing Tailwind utilities

## Notes
- Generic (non-CV-specific) `pollJobUntilTerminal` in `lib/profile.ts` matches the backend's deliberately job-generic `JobStatusResponse` (schemas/jobs.py) — good forward fit for P6 crawl/OCR jobs; consider promoting it to a `lib/jobs.ts` when the second consumer lands (cheap follow-up, not a blocker).
- Route auth-gating is client-side only, consistent with the existing `Chat` pattern; the backend enforces `require_auth` on every consumed endpoint, so this is defense-in-depth posture, not a gap.
- No design deviation found; all consumed contracts already existed and were used verbatim, with no backend reshaping (constraint honored).
