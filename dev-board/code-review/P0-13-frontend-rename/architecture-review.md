# Architecture review — P0-13-frontend-rename · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 target structure | `frontend/` is the canonical Next.js App Router path (app-design §8, line 377) | `frontend/` exists at repo root; `frontend-v2/` is gone | None — rename brings repo into §8 conformance |
| A2 | v1/v2 separation | v1 CRA isolated, not migrated in place; deleted at cutover (plan P11, line 184) | v1 CRA lives in `legacy-code/frontend/`, untouched; v2 now occupies `frontend/` | None — coexistence resolved cleanly ahead of P11 |
| A3 | Build wiring (P0-06) | docker-compose frontend service builds the v2 app | `docker-compose.yml:93` `context: ./frontend`; service name `frontend`; `docker compose config` validates | None |
| A4 | CI wiring (P0-10) | frontend-ci targets the v2 app dir | `.github/workflows/frontend-ci.yml` `working-directory: frontend`, path filters + cache-dependency-path all `frontend/` | None |
| A5 | Phase fit | rename was scheduled at P11 cutover; pulling early must not couple to later phases | Pure directory + reference rename; no backend/source coupling introduced | None — early execution is a net positive, deviation tracked in my memory is now resolved |
| A6 | Scope discipline | don't touch `frontend/` source beyond rename; don't touch `legacy-code/` | No source changes; `legacy-code/` untouched; `legacy-code/README.md` cleaned of stale `frontend-v2` refs | None |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — frontend-only path rename; no layering surface touched
- [x] Honors locked decisions — Next.js App Router intact; no ReAct/datastore/auth surfaces affected
- [x] Interfaces-before-implementations — N/A for this task
- [x] Budget posture respected — N/A (no infra/provider change)

## Notes
- **Early rename resolves a tracked deviation.** My standing ruling ([[project-frontend-path]]) said the
  `frontend-v2 → frontend` rename was owed at the P11 cutover gate. P0-12 moved v1 CRA to `legacy-code/`,
  which freed the canonical `frontend/` slot, so doing the rename now is consistent with §8 and with plan
  P11 line 184 (which only requires v1 *removed*, satisfied by `legacy-code/` isolation). No design risk in
  pulling it forward — I am updating my memory accordingly.
- **Follow-up (minor, cheap-to-fix-later, not a gate):** `frontend/package.json` + `package-lock.json` still
  carry `"name": "career-coach-frontend-v2"`. This is an npm package identifier, not a directory path, and §8
  governs structure, not package names — so it is not a design-conformance gap. The engineer correctly left it
  under the "don't touch frontend source" non-goal and flagged the acceptance-criterion tension. Recommend the
  orchestrator log a trivial follow-up to drop the `-v2` suffix (cosmetic) whenever frontend source is next
  edited; not worth its own revision.
- **Remaining `frontend-v2` string hits are all out-of-scope or historical** and correctly left untouched:
  reviewer-authored audit files (`*/code-review.md`, `*/architecture-review.md`), other agents' private memory,
  and self-referential P0-13 task/queue records. These are audit trail, not live code/config — leaving them is
  the right call per the agent-handoff "never edit another agent's file" rule.
- **Out of my lane (defer to code-reviewer):** the `git mv` vs plain `mv` history-preservation question. From a
  design standpoint, history mechanics are not a §8/architecture concern; the engineer's rationale (source was
  untracked, so no history exists to lose) is plausible but the code-reviewer owns that verdict.
