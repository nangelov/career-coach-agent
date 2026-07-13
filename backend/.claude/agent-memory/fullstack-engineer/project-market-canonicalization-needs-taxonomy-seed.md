---
name: project-market-canonicalization-needs-taxonomy-seed
description: Market role canonicalization (_resolve_baseline) searches ALL curated KB docs; live e2e mining tests must seed a taxonomy occupation doc or the read resolves to the wrong role
metadata:
  type: project
---

`market_agent._resolve_baseline` / `resolve_canonical_role` canonicalize a role by
hybrid-searching `shared_kb_document_ids(source_types=["curated"])` — which includes taxonomy
occupations **and** role-profile summaries **and** learning resources (all share
`source_type="curated"`, distinguished only by `meta.kind`).

**Why:** After a role is mined, a role-profile summary doc titled `"Market requirements: <role>"`
exists as a curated doc. On an empty/taxonomy-less DB the read-time canonicalize then resolves to
*that* title (not the mined `role_profiles.canonical_role`), so `get_role_profile` misses and the
requirements endpoint returns a perpetual 202. With the P6-01 taxonomy seed present (the
production condition), the taxonomy occupation doc outranks the summary and canonicalization is
stable (verified empirically).

**FIX-07 (2026-07-13):** `_resolve_baseline` now takes top-k (`BASELINE_SEARCH_K=5`) and picks
the first hit whose parent `KbDocument.meta["kind"] == TAXONOMY_KIND` (no longer rank-only). The
three kind markers (`TAXONOMY_KIND`, `ROLE_PROFILE_KIND`, `LEARNING_RESOURCE_KIND`) are now
single-source in `app/repositories/kb_kinds.py` — never re-define the literal anywhere.

**How to apply:** Any live/e2e test that mines a role then reads it back MUST first seed a
taxonomy occupation doc with `meta["kind"] == TAXONOMY_KIND` (import from `app.repositories.kb_kinds`,
NOT an ad-hoc string like `"occupation"`), `source_type="curated"`, `meta.skills`, title == role —
mirror `_seed_taxonomy_occupation` in `test_p6_exit_verification.py`. A seed missing the correct
`kind` will now be skipped by the filter and canonicalization falls back to the user-stated role.
