---
name: ruling-shared-kb-corpus-discrimination
description: Multiple shared corpora coexist under source_type="curated" and are discriminated by a meta.kind marker; read helpers must filter on kind
metadata:
  type: project
---

The shared KB (`kb_documents`/`kb_chunks`, `user_id IS NULL`) hosts several §5.6/§5.7 corpora
(occupation taxonomy, role-profile summaries, learning resources). They all share
`source_type="curated"` (the `ck_kb_documents_source_type` allowlist is `curated/user_cv/crawled`
— do NOT add per-corpus source_type values), and are distinguished by a **`meta.kind`** marker:
`ROLE_PROFILE_KIND` (market_agent, P6-04), `LEARNING_RESOURCE_KIND="learning_resource"` (P6-06),
taxonomy occupations.

**Why:** keeps the source_type constraint stable/migration-free while letting corpora coexist and
be independently queryable via JSONB containment on `meta`.

**How to apply:** any new shared-KB corpus (a) reuses `source_type="curated"`, (b) stamps a distinct
`meta.kind`, (c) provides a repository read that filters on that kind (containment `@>
{"kind": ..., ...}`) so it never leaks sibling corpora. Blessed layering: idempotent
delete-before-insert + `KbDocument` construction inline in the ingestion pipeline `_persist`
(matching market_agent/taxonomy_seed) is fine; the downstream **read** must live in `repositories/`.
See [[pattern-celery-ingest-composition-root]].
