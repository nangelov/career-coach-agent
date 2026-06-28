# Task P0-05-frontend-nextjs — Scaffold frontend/ Next.js (App Router) + TypeScript

- **Phase:** P0   **Status:** ENG   **Tags:** (F)

## Scope

Replace the old CRA `frontend/` with a fresh **Next.js 14+ App Router** + TypeScript scaffold:
- Init with `npx create-next-app@latest` (App Router, TypeScript, Tailwind CSS, ESLint).
- Configure `next.config.ts` with API proxy rewrite: `/api/**` → `http://localhost:8000/api/**` (dev only).
- Establish the folder layout per §8: `app/`, `components/`, `lib/`, `public/`, `styles/`.
- Add a minimal root layout (`app/layout.tsx`) and a home page (`app/page.tsx`) with a placeholder "Career Coach v2" heading.
- Keep all v1 CRA files intact (do NOT delete `frontend/` yet — v1 removal is P11). Place v2 frontend under `frontend/`.
- `npm run dev` starts the Next.js dev server on port 3000 without errors.
- `npm run build` produces a production build with zero errors.

## Acceptance criteria

- [ ] `frontend/` exists with a valid Next.js App Router + TypeScript project.
- [ ] `npm run dev` (from `frontend/`) starts cleanly on port 3000.
- [ ] `npm run build` succeeds with zero TypeScript or ESLint errors.
- [ ] `next.config.ts` proxies `/api/**` to `http://localhost:8000/api/**` in dev.
- [ ] Root layout and home page render with a "Career Coach v2" heading.
- [ ] Old `frontend/` (CRA) is untouched.

## Design references

- `dev-board/plan.md` — P0 "Repo layout & tooling", P1 "Next.js chat page"
- `dev-board/app-design-and-features.md` — §8 frontend structure, §3 tech stack (Next.js App Router)

## Constraints / non-goals

- No chat UI yet (P1).
- No auth UI (P3).
- Do NOT delete the old CRA `frontend/` — that is P11 cutover.
- No backend integration beyond the proxy rewrite config.
- Keep it minimal — scaffold + correct structure only.
