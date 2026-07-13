# Architecture review — FIX-09-taxonomy-fixture-gitignored · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure (P6-01 seed) | Bundled ESCO/O*NET taxonomy fixture lives at `backend/app/ingestion/data/` and ships in the repo | `git ls-files` now lists `taxonomy_seed.json` + `README.md`; `git check-ignore` on the fixture exits non-zero | None — fixture is genuinely tracked, matching the P6-01 seed design (see [[project-taxonomy-seed]]) |
| A2 | gitignore scoping | `data/` ignore intended only for the root runtime artifact dir, not any nested source `data/` | Anchored to `/data/`; root `data/` still ignored (exit 0), nested source dir no longer shadowed | None |
| A3 | Other casualties | No other legitimate source dir silently excluded by the broad pattern | Only source-tree `data/` dirs are `./data` (root, intentionally ignored) and the fixture; all other hits are under `.venv/` (ignored by its own rule) | None |
| A4 | Scope / non-goals | gitignore + missing-commit fix only; no product/layering change | Diff limited to `.gitignore` + two tracked fixture files; no product code | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — no code paths touched; restores P6-01's intended tree state
- [x] Honors locked decisions — no stack/orchestration/auth surface involved
- [x] Interfaces-before-implementations — N/A (infra fix)
- [x] Budget posture respected — N/A (no new services)

## Notes
- Anchoring `/data/` over a `!`-negation is the correct minimal choice: it also protects any future
  legitimate nested `data/` dir instead of whitelisting a single path. Blessed as the pattern for this repo.
- This fix makes P6-01 actually merged into the tree CI/clones see; the fixture was previously present only
  as an untracked local artifact, which is why the bug escaped local runs. Design intent of P6-01 is
  unchanged and now correctly realized.
