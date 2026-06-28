---
name: project-frontend-path
description: v2 frontend now lives at canonical §8 path frontend/ (renamed from frontend-v2/ at P0-13); v1 CRA isolated in legacy-code/
metadata:
  type: project
---

**RESOLVED as of P0-13 (approved 2026-06-28).** The §8 canonical frontend path is **`frontend/`**, and v2 now
occupies it. History: v2 was scaffolded at **`frontend-v2/`** (P0-05) for coexistence, then P0-12 moved the v1
CRA into `legacy-code/frontend/`, which freed the canonical slot. P0-13 renamed `frontend-v2/` → `frontend/` and
fixed all live references (`docker-compose.yml` context `./frontend`, `frontend-ci.yml` working-directory).

**Why the early rename was blessed:** plan P11 (line 184) only requires v1 *removed* — satisfied by `legacy-code/`
isolation — so pulling the rename forward from P11 is consistent with §8 and introduces no later-phase coupling.

**How to apply:** `frontend/` is now correct — do NOT expect or require `frontend-v2/`. Residual `frontend-v2`
string hits are acceptable: `frontend/package.json` `"name": "career-coach-frontend-v2"` (npm identifier, not a
path — cosmetic follow-up, not a §8 gap) and historical audit files/agent memories. See [[project-v2-locked-stack]].

Also noted at P0-05: Next.js pinned to 15.x (not @latest/16) due to Node 18.19.1 runtime; satisfies "Next.js 14+".
If the P11 deploy target standardizes on Node 20+, a Next 16 upgrade becomes a reasonable follow-up.
