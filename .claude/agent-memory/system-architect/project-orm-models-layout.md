---
name: project-orm-models-layout
description: Blessed P2-03 repository-models layout (repositories/models/<group>.py subpackage) + identity schema rulings for P2-04/05 consistency
metadata:
  type: project
---

**Blessed at P2-03 (identity migration).** ORM models live in a `backend/app/repositories/models/`
subpackage, one module per table group (`identity.py` = P2-03; `knowledge.py`/`dashboard.py` follow in
P2-04/05). This extends §8's flat `repositories/postgres.py` layout but stays within the repository layer —
**accepted, do not re-litigate.** `models/__init__.py` imports every module so `import app.repositories.models`
fully populates `Base.metadata` (single Alembic target). Migrations chain sequentially: `0001` baseline (P2-02)
→ `0002` identity (P2-03).

**Why:** keeps `env.py`/tests to one import for full-schema autogenerate; scales per table group.
**How to apply:** for P2-04/05 expect a new `models/<group>.py` module + one import line in `models/__init__.py`;
gate that the migration's `down_revision` chains onto the prior head, JSONB (not JSON) is used, and pgvector
columns are `vector(4096)` per [[project-v2-locked-stack]] decision #3.

**P2-04 (knowledge) blessed:** `models/knowledge.py` (`KbDocument`/`KbChunk`/`UserMemory`) + migration `0003`→`0002`. `metadata` col → Python attr `meta` (name reserved on Base). `kb_chunks.content_tsv` = generated STORED tsvector + GIN. Both `embedding` = `vector(4096)`. GDPR: `user_id` CASCADE (NULL=shared curated, survives); `source_message_id`→`messages.message_id` SET NULL. **4096-dim ANN ruling (don't reopen):** pgvector HNSW caps at 2000 dims (`vector`)/4000 (`halfvec`), so a plain `vector_cosine_ops` HNSW at 4096 is impossible. Blessed pattern = binary-quantize HNSW (`binary_quantize(embedding)::bit(4096) bit_hamming_ops`) as ANN *prefilter* + exact cosine (`<=>`) rerank on the full-precision column; honors the locked dim=4096 (no truncation). Functional indexes created via raw SQL in migration + excluded from autogenerate via `env.py` `include_object`/`_UNMODELED_INDEXES`.

**P2-05 (structured records) blessed:** `models/jobs.py` (`Job`) + `models/dashboard.py` (`Pdp`/`Goal`/`Milestone`/`DashboardTask`/`ProgressEntry`) + migration `0004`→`0003`. Plain relational + JSONB, no pgvector (§4 lists jobs/pdps/dashboard as non-vector). Blessed rulings (don't reopen): (1) `jobs` = **global unscoped cache, no `user_id`** (untouched by GDPR user-delete); per-user match score deferred to a future `user_job_matches(user_id,job_id,score)` join table — do NOT add `user_id` to `jobs`. (2) jobs dedup key = `UniqueConstraint(source, external_id)`, not `source_url` (URLs redirect); crawled rows get synthetic `(source='crawl', external_id=<url-hash>)`. (3) `source`(`user`|`ai`) checked-varchar on all 4 dashboard entities (superset of §5.2's `tasks`-minimum) + `'proposed'` seeded in every status vocab so the P9 proposed→approve workflow needs no later migration. (4) `tasks.goal_id` NOT NULL CASCADE + `tasks.milestone_id` nullable SET NULL (task survives milestone delete under goal). (5) `progress_entries` append-only (no `updated_at`), `goal_id`/`task_id` SET NULL so log outlives plan edits, `user_id` CASCADE. (6) ORM class `DashboardTask`→table `tasks`, deliberately distinct from Celery `app/tasks/`.

**Identity schema rulings already blessed (don't reopen):** no password column on `users` (SSO-only §7.1);
unique `(provider,sub)`; `messages.message_id` = `String(32)` unique matching `uuid4().hex`; `sessions.id` =
`String(64)` client-supplied (`crypto.randomUUID()`), nullable `user_id` = guest; `role`/`rating` as
`CheckConstraint` over `String` (kept in lockstep with `app.llm.types.Role`), not PG `ENUM`; GDPR user-delete
CASCADEs owned rows, but product `feedback` FKs are `ON DELETE SET NULL` (deliberately outlives the account).
