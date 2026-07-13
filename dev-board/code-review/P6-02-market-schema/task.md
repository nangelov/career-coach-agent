# Task P6-02-market-schema — role_profiles + job_postings migration
- **Phase:** P6   **Status:** ENG   **Tags:** (B)
## Scope
tasks.md P6 bullets 2 + 3:
- **`role_profiles`** (new): canonical role + taxonomy id, `requirements JSONB` (skill → frequency/weight/
  evidence), `sources`, `evidence_count`, `refreshed_at`. **Global, not user-scoped** (no `user_id`).
- **`job_postings`** (rename of the existing P2-05 `jobs` table, see
  `backend/app/repositories/models/jobs.py` / migration `20260705_0004_structured_records.py`): raw **evidence
  only**, TTL-cached, deduped, **third-party PII stripped at ingest** (recruiter name/email/phone — enforced in
  the P6-04 ingestion code, this task only needs the *schema* to support it).

Add a new Alembic migration (next sequential revision after `20260713_0006_consent.py`) that:
1. `op.rename_table("jobs", "job_postings")`, rename the ORM class `Job` → `JobPosting` in
   `repositories/models/jobs.py` (or move it into a new `repositories/models/market.py` alongside
   `RoleProfile` — pick one file and keep both models colocated for the market-intel table group; update every
   import site, e.g. any place that imports `app.repositories.models.jobs.Job`).
2. Drop `match_score` from `job_postings` — P6 explicitly **drops per-posting match scoring** (tasks.md P6
   header: "Dropped: ... per-posting match scoring, GET/POST /api/jobs"). Do not build a `/api/jobs` endpoint.
3. Add to `job_postings`: a `target_role` (`String`, not null — which canonical role this posting was mined as
   evidence for) and an `expires_at` (`DateTime(timezone=True)`, not null — TTL cache expiry) column, both
   indexed appropriately (`target_role` at least).
4. Create `role_profiles`: `id` (UUID PK), `canonical_role` (String, unique — the normalized/taxonomy-matched
   role title), `taxonomy_id` (String, nullable — ESCO/O*NET id from P6-01's seed, if matched), `requirements`
   (JSONB, not null, default `{}` — shape: `{"<skill>": {"frequency": <float 0-1>, "weight": <float>,
   "evidence": [<job_posting id or source url>, ...]}}`), `sources` (JSONB, not null, default `[]` — list of
   source identifiers/urls contributing to this profile), `evidence_count` (Integer, not null, default 0),
   `refreshed_at` (DateTime(timezone=True), nullable), `created_at`/`updated_at`. **No `user_id`** — global,
   shared, never cascaded on user-delete.
5. Update `repositories/postgres.py` re-exports / `__init__.py` wiring if models are re-exported there (check
   how `KbDocument`/`Job` etc. are currently exposed and follow the same pattern for `RoleProfile`).

## Acceptance criteria
- [ ] New Alembic migration applies cleanly on top of the current head; `alembic downgrade -1` reverses it
      cleanly (rename back, re-add `match_score`, drop `role_profiles`).
- [ ] ORM models: `RoleProfile` (new) and `JobPosting` (renamed `Job`) — both under `repositories/models/`,
      following the existing style (`CreatedAtMixin`, explicit `__tablename__`, docstring explaining the
      global/non-personal posture and PII-stripped-at-ingest note referencing §7.6).
- [ ] Every existing import of `app.repositories.models.jobs.Job` (grep the codebase — P5/P2 code and tests)
      is updated to `JobPosting`; no dangling references, no broken tests from the rename.
- [ ] `role_profiles.canonical_role` has a unique constraint (one profile per canonical role — "extraction
      happens once per role, reused across users").
- [ ] Unit/migration tests (mirroring the existing pattern for `20260705_0003`/`0004`) verify the new tables'
      shape and the rename.
- [ ] No `GET`/`POST /api/jobs` endpoints are added or reintroduced — this task is schema-only.

## Design references
- dev-board/plan.md: Phase 6, bullets 2-3  ·  dev-board/app-design-and-features.md §5.6 (`role_profiles`
  paragraph), §4 (structured records posture), §7.6 (PII posture)
- Existing pattern: `backend/migrations/versions/20260705_0004_structured_records.py`,
  `backend/app/repositories/models/jobs.py`

## Constraints / non-goals
- No ingestion/mining logic here (that is P6-04) — schema only.
- Do not touch `kb_documents`/`kb_chunks` (P6-01's territory, landing in parallel).
- Do not build the `role_profiles` embedding write path here (P6-04 embeds into `kb_chunks` once it aggregates).
