---
name: ruling-market-cache-key-raw-param
description: Roles/market response cache keys on cheap raw-param normalization, NOT the taxonomy canonical — blessed
metadata:
  type: project
---

The `/api/roles/{role}/requirements` Redis response cache (P6-07 `RolesService._cache_key`)
keys on a cheap whitespace-folded lowercased raw path param, **not** the taxonomy
`canonical_role`.

**Why:** canonicalization (`market_agent.resolve_canonical_role`) itself reads Postgres
(embedder taxonomy hybrid-search), so keying on the canonical would force every cache "hit" to
re-hit the DB and defeat §5.7 "cache hot roles" (and the acceptance test asserting DB not hit
twice). Two spellings that canonicalize to the same role get two cheap cache entries — harmless;
each still resolves to one `role_profiles` row on a miss.

**How to apply:** don't flag the "cache key isn't canonical" as an inconsistency in future
market/roles work — it is deliberate and correct. The read order is: Redis (raw key) → miss →
canonicalize → `get_role_profile(canonical)`. See [[pattern-worker-node-di-scope]] for the
retrieval-only worker analogue. Related: [[ruling-shared-kb-corpus-discrimination]].
