# Architecture review — P6-09-manual-verify · engineer revision 1

## Verdict: APPROVED

Verification-only task (T). No product code changed — one new composed exit test
(`backend/tests/test_p6_exit_verification.py`) plus `ruff format` whitespace cleanup on 6 pre-existing
P6 files. The deliverable meets its acceptance criteria and correctly **surfaces** the one real gap it
found instead of patching around it (task.md line 57-61 explicitly asked for this).

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | test lives in `backend/tests/`, mirrors P4-10/P5-08 shape | `test_p6_exit_verification.py`, real stack + fake external edges only | none |
| A2 | §5.6 / §1.1 — market-intel not a job board | no listings surface anywhere; MARKET_INTEL worker returns only role-profile-derived requirements | proven 3 ways (worker payload keys, backend OpenAPI = only `/api/jobs/status/{task_id}`, frontend source scan) | none |
| A3 | §7.5 — no request-path crawl | mine is Celery-only; read serves cache, cold role → 202 + one enqueue | asserted (`resolver.calls==1`, `enqueuer.calls==[]` on cache hit; 202 + single enqueue cold) | none |
| A4 | locked decisions | forced tool-call extraction (no ReAct parser), Postgres+pgvector, in-process embedder, budget=OSS | honored; live tests use `vector(4096)`, fake only external edges | none |
| A5 | §5.6 canonicalization consistency | mine and read must resolve the **same** canonical role via a taxonomy-only match | `_resolve_baseline` matches over `source_types=["curated"]`, which also contains role-profile summaries + learning resources — filters on `source_type`, not `meta.kind` | **real gap — route to P6-04 (see Notes).** Not blocking *this* task. |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (tests drive real Router→Service→Repo/Agent, fake only edges)
- [x] Honors locked decisions (no ReAct parser; Postgres+Redis only; SSO-only untouched; in-process embeddings)
- [x] Interfaces-before-implementations (drives real seams: `mine_role_requirements`, `RolesService`, `GraphTurnStreamer`, market/learning repos)
- [x] Budget posture respected (no live HF/Tavily creds; fakes on external edges)

## Notes

**On the flagged P6-04 observation — it is a genuine conformance gap, not merely a robustness nicety, but it is correctly *deferred* out of P6-09.**

The engineer's read is accurate. `_resolve_baseline` (market_agent.py:449) calls
`shared_kb_document_ids(session, source_types=["curated"])`, which returns the taxonomy occupations
**plus** the role-profile summary docs (`ROLE_PROFILE_SOURCE_TYPE="curated"`, market_agent.py:103)
**plus** learning resources — all three share `source_type="curated"` and are distinguished only by
`meta.kind`. The read filters on `source_type`, never on `meta.kind`, so it leaks sibling corpora into
the taxonomy match and relies on ranking to pick the occupation doc over a summary titled
`"Market requirements: <role>"` that contains the exact role phrase.

This directly violates the blessed ruling **shared-KB kind-discrimination** (my memory
`ruling-shared-kb-corpus-discrimination`): *any read over the shared curated corpus must filter on
`meta.kind` (`@> {"kind": ...}`) so it never leaks sibling corpora.* The production failure mode the
engineer describes — a role with no matching taxonomy occupation canonicalizing to a summary's title,
missing `get_role_profile`, and looping on 202 — is real. `shared_kb_document_ids` today has no `kind`
parameter, so the fix is small and self-contained: add a `meta` containment filter and pass an
occupation `kind` from `_resolve_baseline`.

**Why this does not block P6-09:** the task is verification-only and its acceptance criteria explicitly
require flagging a prior-task gap precisely rather than silently patching it — which the engineer did,
naming P6-04 and the exact seam. Blocking the verification task for a defect in already-closed product
code would be the wrong gate. The exit criterion holds under the production condition (P6-01 taxonomy
seeded), empirically confirmed against live Postgres.

**Required orchestrator action (not an engineer fix on this task):** reopen / route a follow-up to
**P6-04** — restrict `_resolve_baseline`'s taxonomy match by `meta.kind` (occupation), not `source_type`
alone, per the kind-discrimination ruling. Do not close this gap silently.
