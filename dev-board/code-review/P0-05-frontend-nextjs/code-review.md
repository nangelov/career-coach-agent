# Code review — P0-05-frontend-nextjs · engineer revision 1

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | nit | frontend-v2/tailwind.config.ts:4-7 | `content` globs cover `app/` and `components/` but not the §8 `styles/` placeholder dir. If shared styles/components are later added under `styles/`, Tailwind classes there will be silently purged from the build. | When `styles/` starts holding real `.{ts,tsx,css}` content (P1+), add `./styles/**/*.{js,ts,jsx,tsx,mdx}` to `content`. No action needed now (dir is empty). |
| C2 | nit | frontend-v2/package.json:13-14 | `next`/`react`/`react-dom` pinned to exact versions while devDeps use carets. Exact pins are fine (and arguably good for reproducibility, backed by the committed lockfile), just inconsistent with the rest of the manifest. | Optional: keep as-is for reproducibility, or align style. Lockfile already guarantees reproducible installs. |

## Notes
- **Acceptance criteria — all met and verified:**
  - `npm run lint` → `✔ No ESLint warnings or errors` (re-run, exit 0).
  - `npm run build` → `✓ Compiled successfully`, static routes `/` (120 B) and `/_not-found`, exit 0 (re-run).
  - `next.config.ts` rewrites `/api/:path*` → `http://localhost:8000/api/:path*`, correctly gated to `NODE_ENV === "development"` (returns `[]` otherwise) — verified in source.
  - `app/layout.tsx` + `app/page.tsx` render the `Career Coach v2` heading; `metadata.title = "Career Coach v2"` set — verified in source.
  - Old CRA `frontend/` untouched: `git diff --stat frontend/` and `git status --short frontend/` both empty.
  - Valid App Router + TS project (`tsconfig.json` strict, `@/*` alias; `app/` layout).
- **Security:** no secrets committed; `.env*` gitignored; `node_modules/`, `.next/`, `next-env.d.ts` gitignored; `package-lock.json` committed (not ignored). Proxy destination is hardcoded `localhost:8000` but dev-only, so no untrusted-host/SSRF exposure in production. No arbitrary-execution surface in a scaffold.
- **`npm audit`:** 2 moderate only, both in a `postcss` copy vendored *inside* `next`'s own `node_modules`; the only "fix" downgrades Next to 9.x (breaking, not actionable). Confirmed independently. No high/critical. Engineer's CVE claim (pinning 15.5.19 over 15.5.4) is consistent.
- **Environment note:** verified Node `v18.19.1` locally, which matches the engineer's rationale for pinning Next 15.5.x + Tailwind 3.4 instead of the Node-20-requiring `create-next-app@latest` (Next 16 / Tailwind 4 oxide). Reasonable, well-justified deviation; "Next.js 14+" still satisfied.
- The task literally asked to init via `create-next-app@latest`; the engineer hand-scaffolded equivalent output instead. The substituted toolchain/version question is a tech-stack conformance call — flagging for the **system-architect's** lane, not gating here. The produced structure matches the requested §8 layout (`app/`, `components/`, `lib/`, `public/`, `styles/`).
- Both findings are nits; neither blocks. No blocker/major defects found.
