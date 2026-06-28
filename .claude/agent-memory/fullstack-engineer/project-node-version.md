---
name: project-node-version
description: Local env runs Node 18.19.1 — pin Next.js to 15.x; create-next-app@latest installs Next 16 which needs Node >= 20.9
metadata:
  type: project
---

The dev/CI environment runs **Node 18.19.1** (npm 9.2.0). Pin frontend tooling to versions that run on Node 18.18+.

**Why:** `create-next-app@latest` installs **Next 16** (engines `node >= 20.9.0`) and Tailwind 4 (`@tailwindcss/oxide` needs Node >= 20). On P0-05 these failed `next typegen`/build on Node 18.19.1. Next **15.5.x** (engines `^18.18.0 || ^19.8.0 || >= 20`) builds and runs cleanly on this Node.

**How to apply:** For `frontend/` (Next.js App Router; renamed from `frontend-v2/` in P0-13), stay on Next **15.5.x** with React 19, Tailwind **3.4.x** (PostCSS-based), ESLint 8 + `.eslintrc.json` until the runtime is upgraded to Node 20+. If a HF Spaces Dockerfile later sets Node 20, Next 16 becomes viable. Also: pick the latest 15.5 patch (15.5.19 at P0-05) to avoid CVE-2025-66478 in earlier 15.5.x.
