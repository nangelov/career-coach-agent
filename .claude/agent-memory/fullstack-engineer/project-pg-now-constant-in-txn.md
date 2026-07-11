---
name: project-pg-now-constant-in-txn
description: Postgres now()/CURRENT_TIMESTAMP is constant within a transaction — rows inserted together share created_at, so ordering tests must set explicit timestamps
metadata:
  type: project
---

Postgres `now()` / `func.now()` (the `created_at` server_default on `CreatedAtMixin`)
returns the **transaction start time**, so multiple rows inserted+committed in ONE
`async with provider.session()` block all get the **same** `created_at`.

**Why it bit us (P3-05):** an integration test inserted 3 feedback rows in one transaction
and asserted newest-first insertion order. The adapter orders `created_at DESC, id DESC`;
with identical timestamps the tiebreaker is the random UUID `id`, so insertion order was
NOT preserved and the assert flaked/failed.

**How to apply:** when writing a live-DB test that asserts time ordering, give each row an
**explicit, spaced** `created_at` (e.g. `base + timedelta(seconds=i)`) rather than relying
on the server default. Don't assume insert order == `created_at` order for same-transaction
rows. Corollary for adapters: a secondary sort key (e.g. `id DESC`) only disambiguates
equal timestamps arbitrarily — it is not a stable insertion-order proxy.
