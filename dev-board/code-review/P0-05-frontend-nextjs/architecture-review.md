# Architecture review — P0-05-frontend-nextjs · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §3 tech stack | Frontend = Next.js (App Router) + React + TypeScript, streaming UI | Next.js 15.5.19, App Router (`app/`), React 19, TypeScript 5 scaffolded | None — satisfies "Next.js 14+"; streaming UI deferred to P1 per scope |
| A2 | §8 structure | `frontend/` with `app/`, `components/`, `lib/`, `package.json` | `app/`, `components/`, `lib/`, `public/`, `styles/`, `package.json` all present | None — superset of §8; `public/`/`styles/` are standard, `.gitkeep` placeholders are harmless |
| A3 | §8 path name | Frontend at `frontend/` | Lives at `frontend-v2/`, v1 CRA `frontend/` left intact | Intentional deviation per task scope (v1 removal/cutover = P11). Cheap to unwind (a rename). Logged as follow-up — not blocking |
| A4 | §9 API surface | v2 API mounted under `/api` | `next.config.ts` dev-only rewrite `/api/:path*` → `http://localhost:8000/api/:path*`, `[]` in prod | None — correct; prod routing left to single-container Dockerfile (§9/P11) |
| A5 | Phase fit (P0/P1) | P0 scaffold only; chat/auth UI later | Placeholder home page + root layout, "Career Coach v2" heading; no chat (P1), no auth (P3) | None — foundation-first sequencing respected, no premature coupling |
| A6 | v1 isolation | Do not migrate v1 in place; stand up v2 alongside (plan §"Don't migrate in place") | `git diff --stat frontend/` empty; v1 CRA untouched | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — frontend scaffold; backend layering N/A
- [x] Honors locked decisions — no backend concerns touched (no ReAct parser, datastores, SSO, embeddings in scope); proxy targets `/api` per §9
- [x] Interfaces-before-implementations — N/A for a scaffold; `lib/` reserved for the SSE api client + auth (§8) in P1/P3
- [x] Budget posture respected — Next.js / React / Tailwind / ESLint all free/OSS/self-hosted; no managed/paid services introduced

## Notes
- **P11 follow-up (non-blocking):** the §8 canonical path is `frontend/`. The scaffold lives at `frontend-v2/` to keep v1 intact, exactly as the task directed. The cutover task (P11) must rename `frontend-v2/` → `frontend/` (and update Dockerfile/compose build paths) when v1 is deleted. Recorded here so the rename is not forgotten; this is the expected, cheap-to-unwind deviation, not a gap.
- **Next 15 vs Next 16 pin:** engineer pinned 15.5.19 (latest 15.5 patch, clears CVE-2025-66478) instead of `@latest` (16) due to the Node 18.19.1 runtime requiring Node ≥20.9 for Next 16 / Tailwind 4. Satisfies "Next.js 14+". Design-acceptable; flag for code-reviewer's correctness lane (runtime/version posture), not an architecture concern. If the deploy target (P11) standardizes on Node 20+, revisiting the Next 16 upgrade is a reasonable later follow-up.
- `globals.css` kept in `app/` (Next convention) with an empty `styles/` reserved for shared styles — consistent with §8 intent.
