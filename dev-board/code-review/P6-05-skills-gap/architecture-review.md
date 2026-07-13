# Architecture review — P6-05-skills-gap · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §8 structure | typed contract in `app/schemas/`, comparison logic in `app/services/`, DB read via `app/repositories/` | `schemas/skills_gap.py` (Pydantic contract), `services/skills_gap.py` (pure fn + wrapper), role read via `repositories.market.get_role_profile` | none |
| A2 | §8 layering Router→Service→Repo | service off the DB driver; no SQLAlchemy in service body | wrapper depends only on `ProfileStore` port + `SessionProvider` Protocol + repo helper; no ORM/`select` in service | none |
| A3 | §5.6 skills gap | `user profile △ role_profile → feeds PDP`; requirements carry frequency/weight/evidence; pure read+compare, no mining trigger | `compute_skills_gap` partitions matched/gap, gap carries verbatim freq/weight/evidence ordered most-in-demand first; wrapper never enqueues Celery | none |
| A4 | Interfaces-before-impl | real seams, not concrete coupling | `ProfileStore` ABC reused; local `SessionProvider` structural Protocol (mirrors the blessed worker-node seam); typed result not raw dict | none |
| A5 | §5.1 graceful degradation | no-profile / no-role_profile handled without raising | `status` = `ok`/`profile_missing`/`role_profile_missing`, `gap=None` on the two missing states; malformed JSONB freq/weight→0.0, non-list evidence→[] | none |
| A6 | Budget posture (§11) | no ML matcher for this task | normalized `strip().lower()` string compare, documented simplification behind a stable contract | none |
| A7 | Data ownership (§4/§7) | user-scoped profile; role_profiles global | profile via `ProfileStore.get(user_id)` (user-keyed); role read is the global `role_profiles` row | none |
| A8 | Phase fit / non-goals | no new route/Celery/migration; P6-07 owns endpoint + refresh policy | none added; degradation states hand the "enqueue mining / prompt CV" decision to P6-07 | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (Postgres+Redis only; no ReAct parser touched; in-process posture unaffected)
- [x] Interfaces-before-implementations (`ProfileStore` ABC, `SessionProvider` Protocol, typed `SkillsGapResult`)
- [x] Budget posture respected (pure string compare, no embedding/fuzzy ML)

## Notes
- Pure/wrapper split, graceful `status` degradation, and repository-only DB access match the P4/P5 seam
  patterns already blessed (worker-node DI + composition-root). Consistent — no re-litigation.
- Follow-up (non-blocking, DRY): the 2-line `SessionProvider` structural Protocol is now duplicated in four
  modules (`services/skills_gap.py`, `tasks/profile_ingest.py`, `agents/rag_agent.py`,
  `ingestion/taxonomy_seed.py`). Duplication is deliberate (avoids a coupling import and each is trivial), so
  it stays APPROVED — but if it grows, consider a single shared structural `SessionProvider` port. Track, do
  not fix here.
- `matched` keyed by the role's requirement spelling (not the CV's) is the right call — the contract speaks
  one vocabulary for P7's PDP.
