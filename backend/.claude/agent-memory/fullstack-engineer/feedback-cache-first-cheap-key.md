---
name: cache-first-cheap-key
description: Cache-first read endpoints must key the cache on a cheap request-derived value, not on a DB-derived canonical, so a hit short-circuits ALL DB work
metadata:
  type: feedback
---

For a cache-first read endpoint (e.g. `GET /api/roles/{role}/requirements`), key the Redis
response cache on a **cheap deterministic normalization of the raw request param**
(`" ".join(role.strip().lower().split())`), NOT on a DB-derived canonical form.

**Why:** if the cache key is the canonical value and canonicalization itself hits the DB
(here: a taxonomy vector search via the embedder), then every "cache hit" still pays a DB
round-trip — defeating the whole point of "cache hot roles". The acceptance test ("second
request served from Redis, DB not hit twice") only passes if the cache short-circuits before
any resolution. Do the expensive canonicalization only on a cache MISS.

**How to apply:** cache hit → return immediately (zero DB). Cache miss → canonicalize (reuse
the existing normalizer, e.g. [[schemas-independent-of-agents]]-style injected port, never a
second copy), read/enqueue keyed on the canonical, then cache the serialized response under the
cheap key. Two spellings mapping to one canonical just yield two harmless cache entries.
